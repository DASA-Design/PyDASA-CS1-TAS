# `src/` Style + Consistency Audit

Rolling log of the bottom-up style audit across every `src/` module. Each component gets walked through the style checklist, proposed changes are logged here, approved changes are applied to code, and any rename / signature change is flagged as a **breaking change** that propagates up the dependency graph.

## Checklist applied to every component

| #   | Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | Source                                 |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| R15 | Terminology: use**increase** / **decrease** (neutral directional) instead of **improvement** / **degradation** (value-laden). Reason: the dimensional method does not assume the user's goal direction — a rise in theta (occupancy) is neither objectively "better" nor "worse" without a domain objective. Applies to src, tests, docstrings, notebook markdown, and notes. Flag during every component scan; plan the call-site swap once we reach any file that already uses the value-laden pair. | user direction, 2026-04-22             |
| R1  | Docstrings on single lines per bullet / Args / Returns / Raises item; linter owns wrapping                                                                                                                                                                                                                                                                                                                                                                                                                                      | `feedback_docstring_wrapping`        |
| R2  | Acronym substitution in every position (`service→svc`, `request→req`, `response→resp`, `context→ctx`, `configuration→cfg`, `message→msg`, `parameter→param`, `specification→spec`, `environment→env`, `vector→vec`, `lambda→lam`, `variables→vars`, `coefficients→coefs`, `architecture→arch`, `network→net`, `directory→dir`, `sensitivity→sens`, `database→db`, `dataframe→df`)                                                                                      | `feedback_acronyms_throughout_names` |
| R3  | Verb-first function names + up to 5 acronyms; classes use nouns                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | CLAUDE.md                              |
| R4  | Type hints on every function signature                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | CLAUDE.md                              |
| R5  | `_` prefix on local variables + meaningful parameters; NOT on module-level imported names                                                                                                                                                                                                                                                                                                                                                                                                                                     | CLAUDE.md                              |
| R6  | Dataclass / pydantic field comments on their own line ABOVE the field with a blank line between fields; no inline `#`                                                                                                                                                                                                                                                                                                                                                                                                         | `coding-conventions.md`              |
| R7  | Keep inline comments at field-declaration sites even when "obvious" (first-definition pedagogy)                                                                                                                                                                                                                                                                                                                                                                                                                                 | user direction, 2026-04-22             |
| R8  | No inline ternaries (`A if cond else B`); use `if`/`else` blocks or early-return                                                                                                                                                                                                                                                                                                                                                                                                                                          | `feedback_no_inline_ternaries`       |
| R9  | Section banner comments (`# ---- Label ---`) stay; they section files for human auditors                                                                                                                                                                                                                                                                                                                                                                                                                                      | user direction, 2026-04-22             |
| R10 | No em-dashes (`—`, U+2014) anywhere in source, docstrings, comments, print strings                                                                                                                                                                                                                                                                                                                                                                                                                                           | `coding-conventions.md`              |
| R11 | Multi-condition booleans: decompose into named `_bool_a` / `_bool_b` vars, combine in final expression                                                                                                                                                                                                                                                                                                                                                                                                                      | `coding-conventions.md`              |
| R12 | Stdlib + first-party imports at module top, grouped by section (`# native python modules` / `# web stack` / `# local modules`); lazy-import only for circular breakers or heavy optional deps                                                                                                                                                                                                                                                                                                                             | `coding-conventions.md`              |
| R13 | Trivial getters =`@property`, not verb methods                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | `coding-conventions.md`              |
| R14 | British English in prose / docstrings (behaviour, analyse, modelling, colour)                                                                                                                                                                                                                                                                                                                                                                                                                                                   | `style-polish.md`                    |
| R16 | `#` comment density: one line per `#` comment, never a run. Stacked `# ...` runs (two or more consecutive comment lines) are forbidden; collapse to one short why-line above the code or drop it. Exceptions: R9 section banners and import-group headers (`# native python modules`, `# scientific stack`, `# web stack`, `# shared view helpers`, `# local modules`, `# test stack`, `# modules under test`, `# target under test`, `# data types`). Dataclass field comments follow the same rule (R6/R7 preserved, but never multi-line). | user direction, 2026-04-24            |

Test files (`tests/<pkg>/test_<mod>.py`) are walked in the same pass as their src partner — one source module plus its test module per stage. Demos (`src/scripts/demo_<mod>*.py`) get walked after the underlying module is closed.

## Step 1 — Component inventory

```
src/
├── __init__.py
├── analytic/
│   ├── __init__.py
│   ├── jackson.py
│   ├── metrics.py
│   └── queues.py
├── dimensional/
│   ├── __init__.py
│   ├── coefficients.py
│   ├── engine.py
│   ├── networks.py
│   ├── reshape.py
│   ├── schema.py
│   └── sensitivity.py
├── experiment/
│   ├── __init__.py
│   ├── client.py
│   ├── instances/
│   │   ├── __init__.py
│   │   ├── tas.py
│   │   └── third_party.py
│   ├── launcher.py
│   ├── payload.py
│   ├── registry.py
│   └── services/
│       ├── __init__.py
│       ├── atomic.py
│       ├── base.py
│       ├── composite.py
│       └── instruments.py
├── io/
│   ├── __init__.py
│   └── config.py
├── methods/
│   ├── __init__.py
│   ├── analytic.py
│   ├── dimensional.py
│   ├── experiment.py
│   └── stochastic.py
├── scripts/
│   ├── demo_client.py
│   ├── demo_payload.py
│   ├── demo_registry.py
│   ├── demo_services.py
│   ├── demo_tas.py
│   └── demo_third_party.py
├── stochastic/
│   ├── __init__.py
│   └── simulation.py
├── utils/
│   ├── __init__.py
│   └── mathx.py
└── view/
    ├── __init__.py
    ├── dc_charts.py
    └── qn_diagram.py
```

Total: 37 source modules + 6 demo scripts = 43 files (excluding `__init__.py` re-exports we'll still check).

## Step 2 — Dependency map

Edges: `importer -> imported`. Only intra-`src/` edges shown; stdlib / third-party (`numpy`, `httpx`, `fastapi`, `pydantic`, `matplotlib`, `networkx`, `simpy`, `pydasa`) omitted.

### Leaves (Stage 0 — zero intra-src deps)

| Module                              | Imports          |
| ----------------------------------- | ---------------- |
| `src/utils/mathx.py`              | —               |
| `src/io/config.py`                | —               |
| `src/experiment/payload.py`       | —               |
| `src/experiment/registry.py`      | —               |
| `src/dimensional/schema.py`       | — (pydasa only) |
| `src/dimensional/coefficients.py` | —               |
| `src/dimensional/engine.py`       | —               |
| `src/dimensional/sensitivity.py`  | —               |
| `src/dimensional/reshape.py`      | —               |
| `src/view/qn_diagram.py`          | —               |

### Stage 1

| Module                              | Imports                                                     |
| ----------------------------------- | ----------------------------------------------------------- |
| `src/analytic/queues.py`          | `utils.mathx`                                             |
| `src/experiment/services/base.py` | — (web-stack only)**[partially audited 2026-04-22]** |
| `src/view/dc_charts.py`           | `view.qn_diagram`                                         |

### Stage 2

| Module                                     | Imports                            |
| ------------------------------------------ | ---------------------------------- |
| `src/analytic/jackson.py`                | `analytic.queues`, `io.config` |
| `src/experiment/services/instruments.py` | `experiment.services.base`       |
| `src/stochastic/simulation.py`           | `io.config`                      |

### Stage 3

| Module                                | Imports                                                           |
| ------------------------------------- | ----------------------------------------------------------------- |
| `src/experiment/services/atomic.py` | `experiment.services.base`, `experiment.services.instruments` |
| `src/analytic/metrics.py`           | `io`                                                            |
| `src/dimensional/networks.py`       | `analytic.jackson`, `analytic.queues`, `io`                 |

### Stage 4

| Module                                   | Imports                                                      |
| ---------------------------------------- | ------------------------------------------------------------ |
| `src/experiment/services/composite.py` | `experiment.services.atomic`, `experiment.services.base` |

### Stage 5 (re-export packages)

| Module                                  | Re-exports                                                                           |
| --------------------------------------- | ------------------------------------------------------------------------------------ |
| `src/experiment/services/__init__.py` | `atomic`, `base`, `composite`, `instruments`                                 |
| `src/analytic/__init__.py`            | `queues`, `jackson`, `metrics`                                                 |
| `src/stochastic/__init__.py`          | `simulation`                                                                       |
| `src/dimensional/__init__.py`         | `coefficients`, `engine`, `networks`, `reshape`, `schema`, `sensitivity` |
| `src/view/__init__.py`                | `dc_charts`, `qn_diagram`                                                        |
| `src/io/__init__.py`                  | `config`                                                                           |
| `src/utils/__init__.py`               | `mathx`                                                                            |

### Stage 6

| Module                                      | Imports                                                                  |
| ------------------------------------------- | ------------------------------------------------------------------------ |
| `src/experiment/client.py`                | `experiment.payload`, `experiment.registry`, `experiment.services` |
| `src/experiment/instances/tas.py`         | `experiment.services`                                                  |
| `src/experiment/instances/third_party.py` | `experiment.services`                                                  |

### Stage 7

| Module                                   | Imports                                           |
| ---------------------------------------- | ------------------------------------------------- |
| `src/experiment/instances/__init__.py` | `tas`, `third_party`, `services` re-exports |

### Stage 8

| Module                         | Imports                                                                            |
| ------------------------------ | ---------------------------------------------------------------------------------- |
| `src/experiment/launcher.py` | `experiment.instances`, `experiment.registry`, `experiment.services`, `io` |
| `src/experiment/__init__.py` | (not yet inspected)                                                                |

### Stage 9 — methods

| Module                         | Imports                                                                                       |
| ------------------------------ | --------------------------------------------------------------------------------------------- |
| `src/methods/analytic.py`    | `analytic`, `io`                                                                          |
| `src/methods/stochastic.py`  | `analytic.metrics`, `io`, `stochastic`                                                  |
| `src/methods/dimensional.py` | `dimensional`, `io`                                                                       |
| `src/methods/experiment.py`  | `analytic`, `experiment.client`, `experiment.launcher`, `experiment.services`, `io` |

### Stage 10 — demos (and `src/__init__.py`)

Demos are leaves of the runtime graph and depend on whatever they demo. Walk them after their subject module closes; they do not forward breaking changes.

- `src/scripts/demo_payload.py` → `experiment.payload`, `io`
- `src/scripts/demo_registry.py` → `experiment.registry`, `io`
- `src/scripts/demo_services.py` → `experiment.services`
- `src/scripts/demo_third_party.py` → `experiment.instances`, `experiment.services`
- `src/scripts/demo_tas.py` → `experiment.instances`, `experiment.services`
- `src/scripts/demo_client.py` → `experiment.client`, `experiment.launcher`, `experiment.payload`, `experiment.services`, `io`
- `src/__init__.py` → re-exports

## Bottom-up walk order

Stages close strictly bottom up. Breaking-change propagation table sits next to each stage so we know which upstream modules must pick up a rename before the next stage starts.

| Stage  | Component                                              | Mirrored test                                      | Breaking-change upstream                                                                                                                                                                         |
| ------ | ------------------------------------------------------ | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 0.1    | `src/utils/mathx.py`                                 | `tests/utils/test_mathx.py`                      | `analytic.queues`                                                                                                                                                                              |
| 0.2    | `src/io/config.py`                                   | `tests/io/test_config.py`                        | `analytic.jackson`, `stochastic.simulation`, `io.__init__`, `dimensional.networks`, every `methods/*.py`                                                                               |
| 0.3    | `src/experiment/payload.py`                          | `tests/experiment/test_payload.py`               | `experiment.client`, `demo_payload`, `demo_client`                                                                                                                                         |
| 0.4    | `src/experiment/registry.py`                         | `tests/experiment/test_registry.py`              | `experiment.client`, `experiment.launcher`, `demo_registry`, `demo_client`, `tests/experiment/services/test_base.py`                                                                   |
| 0.5    | `src/dimensional/schema.py`                          | `tests/dimensional/test_schema.py`               | `dimensional.__init__`, `methods.dimensional`                                                                                                                                                |
| 0.6    | `src/dimensional/coefficients.py`                    | `tests/dimensional/test_coefficients.py`         | `dimensional.__init__`, `methods.dimensional`                                                                                                                                                |
| 0.7    | `src/dimensional/engine.py`                          | `tests/dimensional/test_engine.py`               | `dimensional.__init__`, `methods.dimensional`                                                                                                                                                |
| 0.8    | `src/dimensional/sensitivity.py`                     | `tests/dimensional/test_sensitivity.py`          | `dimensional.__init__`, `methods.dimensional`                                                                                                                                                |
| 0.9    | `src/dimensional/reshape.py`                         | `tests/dimensional/test_reshape.py`              | `dimensional.__init__`, `methods.dimensional`                                                                                                                                                |
| 0.10   | `src/view/qn_diagram.py`                             | `tests/view/test_qn_diagram.py`                  | `view.dc_charts`, `view.__init__`, notebooks                                                                                                                                                 |
| 1.1    | `src/analytic/queues.py`                             | `tests/analytic/test_queues.py`                  | `analytic.jackson`, `analytic.__init__`, `dimensional.networks`                                                                                                                            |
| 1.2    | `src/experiment/services/base.py` **(resume)** | `tests/experiment/services/test_base.py`         | `services.instruments`, `services.atomic`, `services.composite`, `services.__init__`, `experiment.client`, `experiment.instances.*`, `experiment.launcher`, `methods.experiment` |
| 1.3    | `src/view/dc_charts.py`                              | `tests/view/test_dc_charts.py`                   | `view.__init__`, notebooks                                                                                                                                                                     |
| 2.1    | `src/analytic/jackson.py`                            | `tests/analytic/test_jackson.py`                 | `analytic.__init__`, `dimensional.networks`, `methods.experiment`                                                                                                                          |
| 2.2    | `src/experiment/services/instruments.py`             | `tests/experiment/services/test_instruments.py`  | `services.atomic`, `services.__init__`                                                                                                                                                       |
| 2.3    | `src/stochastic/simulation.py`                       | `tests/stochastic/test_simulation.py`            | `stochastic.__init__`, `methods.stochastic`                                                                                                                                                  |
| 3.1    | `src/experiment/services/atomic.py`                  | `tests/experiment/services/test_atomic.py`       | `services.composite`, `services.__init__`, `experiment.instances.third_party`                                                                                                              |
| 3.2    | `src/analytic/metrics.py`                            | `tests/analytic/test_metrics.py`                 | `analytic.__init__`, `methods.analytic`, `methods.stochastic`, `methods.experiment`                                                                                                      |
| 3.3    | `src/dimensional/networks.py`                        | `tests/dimensional/test_networks.py`             | `dimensional.__init__`, `methods.dimensional`                                                                                                                                                |
| 4.1    | `src/experiment/services/composite.py`               | `tests/experiment/services/test_composite.py`    | `services.__init__`, `experiment.instances.tas`                                                                                                                                              |
| 5.1-7  | re-export `__init__.py` packages                     | (no dedicated tests)                               | —                                                                                                                                                                                               |
| 6.1    | `src/experiment/client.py`                           | `tests/experiment/test_client.py`                | `experiment.launcher`, `methods.experiment`, `demo_client`                                                                                                                                 |
| 6.2    | `src/experiment/instances/tas.py`                    | `tests/experiment/instances/test_tas.py`         | `experiment.launcher`, `demo_tas`                                                                                                                                                            |
| 6.3    | `src/experiment/instances/third_party.py`            | `tests/experiment/instances/test_third_party.py` | `experiment.launcher`, `demo_third_party`                                                                                                                                                    |
| 8.1    | `src/experiment/launcher.py`                         | `tests/experiment/test_launcher.py`              | `methods.experiment`, `demo_client`                                                                                                                                                          |
| 9.1    | `src/methods/analytic.py`                            | `tests/methods/test_analytic.py`                 | notebook `01-analytic.ipynb`                                                                                                                                                                   |
| 9.2    | `src/methods/stochastic.py`                          | `tests/methods/test_stochastic.py`               | notebook `02-stochastic.ipynb`                                                                                                                                                                 |
| 9.3    | `src/methods/dimensional.py`                         | `tests/methods/test_dimensional.py`              | notebooks `03-dimensional.ipynb`, `04-yoly.ipynb`                                                                                                                                            |
| 9.4    | `src/methods/experiment.py`                          | `tests/methods/test_experiment.py`               | notebook `05-experiment.ipynb`                                                                                                                                                                 |
| 10.1-6 | `src/scripts/demo_*.py`                              | (no tests)                                         | —                                                                                                                                                                                               |

## Process per component

For each stage cell:

1. **Read** the source module + its mirrored test module.
2. **Scan** each rule R1-R14; list every violation with line number and current vs proposed text.
3. **Propose changes** in this log under the component's section.
4. **Wait for approval.**
5. **Apply** — src first, then the mirrored test, then any demo script that directly consumes the module.
6. **Log breaking changes** (any rename / signature shape change) under "Breaking changes pending" below — so the next stage up knows to swap call-sites.
7. **Close** the component — from this point no further edits unless a downstream stage uncovers a contract violation.

## Progress

| Stage      | Component                                  | Status                                                                                                                                                                                                               | Date       |
| ---------- | ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| 0.1        | `src/utils/mathx.py`                     | closed (non-rename violations;`gfactorial` rename dropped per user direction)                                                                                                                                      | 2026-04-22 |
| 1.2        | `src/experiment/services/base.py`        | closed (non-rename violations)                                                                                                                                                                                       | 2026-04-22 |
| 1.2        | `tests/experiment/services/test_base.py` | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.2        | `src/io/config.py`                       | closed (non-rename violations)                                                                                                                                                                                       | 2026-04-22 |
| 0.2        | `tests/io/test_config.py`                | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.3        | `src/experiment/payload.py`              | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.3        | `tests/experiment/test_payload.py`       | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.4        | `src/experiment/registry.py`             | closed (non-rename + local R3 rename `filter_names_by_role` -> `filter_names_role`; one field-comment inconsistency flagged for user)                                                                            | 2026-04-22 |
| 0.4        | `tests/experiment/test_registry.py`      | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.5        | `src/dimensional/schema.py`              | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.5        | `tests/dimensional/test_schema.py`       | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.6        | `src/dimensional/coefficients.py`        | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.6        | `tests/dimensional/test_coefficients.py` | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.7        | `src/dimensional/engine.py`              | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.7        | `tests/dimensional/test_engine.py`       | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.8        | `src/dimensional/sensitivity.py`         | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.8        | `tests/dimensional/test_sensitivity.py`  | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.9        | `src/dimensional/reshape.py`             | closed (private `_coef_column` -> `_extract_coef_column` rename applied in-file; public B5 rename deferred)                                                                                                      | 2026-04-22 |
| 0.9        | `tests/dimensional/test_reshape.py`      | closed                                                                                                                                                                                                               | 2026-04-22 |
| 0.10       | `src/view/qn_diagram.py` + test          | **deferred to end of walk** — largest file in `src/view/` and predominantly UI/plotting concerns (matplotlib rcParams, networkx layout, SVG fill quirks) that are orthogonal to the rest of the audit rules | 2026-04-22 |
| 1.1        | `src/analytic/queues.py`                 | closed                                                                                                                                                                                                               | 2026-04-22 |
| 1.1        | `tests/analytic/test_queues.py`          | closed;`TestGFactorial` relocated to new `tests/utils/test_mathx.py` (B2 done)                                                                                                                                   | 2026-04-22 |
| 1.1        | `tests/utils/test_mathx.py`              | NEW — created with relocated `TestGFactorial` class                                                                                                                                                               | 2026-04-22 |
| 2.1        | `src/analytic/jackson.py`                | closed (non-rename; B6 R2+R3 public renames deferred)                                                                                                                                                              | 2026-04-22 |
| 2.1        | `tests/analytic/test_jackson.py`         | closed                                                                                                                                                                                                               | 2026-04-22 |
| 2.2        | `src/experiment/services/instruments.py` | closed                                                                                                                                                                                                               | 2026-04-22 |
| 2.2        | `tests/experiment/services/test_instruments.py` | closed                                                                                                                                                                                                        | 2026-04-22 |
| 2.3        | `src/stochastic/simulation.py`           | closed (non-rename; B7 R2+R3 renames deferred)                                                                                                                                                                      | 2026-04-22 |
| 2.3        | `tests/stochastic/test_simulation.py`    | closed                                                                                                                                                                                                               | 2026-04-22 |
| 3.1        | `src/experiment/services/atomic.py`      | closed; mid-audit linter rollback of `pick_target` / `dispatch` extension kwargs broke composite.py → demo_services.py at runtime; restored in follow-up so `project_composite_on_atomic` memory stays current       | 2026-04-22 |
| 3.1        | `tests/experiment/services/test_atomic.py` | closed                                                                                                                                                                                                             | 2026-04-22 |
| 3.2        | `src/analytic/metrics.py`                | closed (non-rename; B9 R2 renames deferred)                                                                                                                                                                         | 2026-04-22 |
| 3.2        | `tests/analytic/test_metrics.py`         | closed                                                                                                                                                                                                               | 2026-04-22 |
| 3.3        | `src/dimensional/networks.py`            | closed (non-rename; B10 R2 + R3 renames deferred)                                                                                                                                                                    | 2026-04-22 |
| 3.3        | `tests/dimensional/test_networks.py`     | closed — already clean on R1-R15                                                                                                                                                                                      | 2026-04-22 |
| 4.1        | `src/experiment/services/composite.py`   | closed (non-rename; B8 rename `mount_composite_service -> mount_composite_svc` deferred)                                                                                                                             | 2026-04-22 |
| 4.1        | `tests/experiment/services/test_composite.py` | closed                                                                                                                                                                                                          | 2026-04-22 |
| 5.*        | 10 `__init__.py` re-export packages      | closed (encoding header added to 3 missing files; `__all__` sorted alphabetically in `analytic` + `io` for consistency with `dimensional` / `experiment.services` / `view`)                                        | 2026-04-22 |
| 6.1        | `src/experiment/client.py`               | closed (non-rename; B11 R2 renames deferred)                                                                                                                                                                         | 2026-04-22 |
| 6.1        | `tests/experiment/test_client.py`        | closed                                                                                                                                                                                                               | 2026-04-22 |
| 6.2        | `src/experiment/instances/tas.py`        | closed                                                                                                                                                                                                               | 2026-04-22 |
| 6.2        | `tests/experiment/instances/test_tas.py` | closed — already clean on R1-R15                                                                                                                                                                                      | 2026-04-22 |
| 6.3        | `src/experiment/instances/third_party.py` | closed                                                                                                                                                                                                              | 2026-04-22 |
| 6.3        | `tests/experiment/instances/test_third_party.py` | closed — already clean on R1-R15                                                                                                                                                                              | 2026-04-22 |
| 6.X        | `tests/experiment/test_logger_integration.py` | closed — cross-cutting FR-3.4 + FR-3.8 integration guard for `@logger` + `flush_log` + on-disk CSV; no 1:1 `src/` mirror. Renamed from `test_journey_log.py` 2026-04-22 because the "journey_log" metaphor was unclear                                                                                                     | 2026-04-22 |
| 7.1        | `src/experiment/instances/__init__.py`   | closed — encoding header added, 2 docstring paragraphs un-wrapped, em-dash + 2 Unicode arrows replaced with ASCII                                                                                                    | 2026-04-22 |
| 8.1        | `src/experiment/launcher.py`             | closed (non-rename; B12 R3 private renames deferred); 5 stale doc references fixed (HTTPException(413) / HttpForward path / CompositeQueue-AtomicQueue / invoke_url / app.state.service)                             | 2026-04-22 |
| 8.1        | `tests/experiment/test_launcher.py`      | closed                                                                                                                                                                                                               | 2026-04-22 |
| 9.1        | `src/methods/analytic.py`                | closed                                                                                                                                                                                                               | 2026-04-22 |
| 9.1        | `tests/methods/test_analytic.py`         | closed                                                                                                                                                                                                               | 2026-04-22 |
| 9.2        | `src/methods/stochastic.py`              | closed                                                                                                                                                                                                               | 2026-04-22 |
| 9.2        | `tests/methods/test_stochastic.py`       | closed                                                                                                                                                                                                               | 2026-04-22 |
| 9.3        | `src/methods/dimensional.py`             | closed (incl. in-file `coeff_specs -> coef_specs` rename on `_analyse_artifact`)                                                                                                                                      | 2026-04-22 |
| 9.3        | `tests/methods/test_dimensional.py`      | closed — already clean on R1-R15                                                                                                                                                                                      | 2026-04-22 |
| 9.4        | `src/methods/experiment.py`              | closed                                                                                                                                                                                                               | 2026-04-22 |
| 9.4        | `tests/methods/test_experiment.py`       | closed — already clean on R1-R15                                                                                                                                                                                      | 2026-04-22 |
| 10.1       | `src/scripts/demo_payload.py`            | closed — already clean on R1-R15                                                                                                                                                                                      | 2026-04-22 |
| 10.2       | `src/scripts/demo_registry.py`           | closed — already clean on R1-R15                                                                                                                                                                                      | 2026-04-22 |
| 10.3       | `src/scripts/demo_services.py`           | closed — stale `@instrumented` -> `@logger` in docstring; 4 `*name()*` lead-ins added; 2 hand-wrapped WHY comments un-wrapped                                                                                         | 2026-04-22 |
| 10.4       | `src/scripts/demo_tas.py`                | closed — already clean on R1-R15                                                                                                                                                                                      | 2026-04-22 |
| 10.5       | `src/scripts/demo_third_party.py`        | closed — `inst` -> `_inst` (R5) on `_mas_spec`                                                                                                                                                                       | 2026-04-22 |
| 10.6       | `src/scripts/demo_client.py`             | closed — 3 hand-wrapped WHY comments un-wrapped                                                                                                                                                                       | 2026-04-22 |
| 11         | `src/__init__.py`                        | closed — already clean on R1-R15 (2-line root-package docstring)                                                                                                                                                      | 2026-04-22 |
| 0.10       | `src/view/qn_diagram.py`                 | closed (R15 terminology sweep applied: `_BAR_GREEN` / `_BAR_RED` -> `_BAR_BLUE` / `_BAR_ORANGE` with pastel values; "improvement" / "degradation" removed from docstring + comment + legend; 10 inline ternaries rewritten; 4 R1 docstring un-wraps; 4 `ax: plt.Axes` annotations; British-English normalised) | 2026-04-22 |
| 0.10       | `tests/view/test_qn_diagram.py`          | **does not exist** — 1300-line matplotlib / networkx module has no mirrored test. Flagged as audit gap; full coverage out of scope for this pass                                                                      | 2026-04-22 |
| all others | —                                         | not started                                                                                                                                                                                                          | —         |

### Stage 0.1 — `src/utils/mathx.py` (closed)

**Applied (2026-04-22):**

- R5: renamed local `result` → `_result` inside `gfactorial` (3 occurrences).
- Removed `# Apply precision if specified` WHAT-comment above the `if prec is not None` block — the code reads itself.

**Kept unchanged:**

- WHY-comments on each dispatch branch (`# Standard factorial for non-negative integers`, `# Factorial is not defined for negative integers`, `# For floats, use the gamma function: Γ(x+1)`) — they explain the mathematical reason each branch exists, not what the code does.
- `# TODO: extend with other generalised special functions as methods grow.` — TODOs are fine.
- Compound-condition `isinstance(x, int) and x >= 0` — 2-condition dispatch is readable inline; R11 decomposition only kicks in for 3+ conditions.

### Stage 1.2 — `src/experiment/services/base.py` (closed)

**Applied (2026-04-22):**

- Earlier: stdlib imports hoisted (`csv`, `Path`); 3 inline ternaries rewritten to `if`/`else` blocks.
- R10: em-dash on section banner "Minimal per-service state —" replaced with semicolon.
- R4: added type hints on `flush_log(csv_path: Path, columns: tuple[str, ...] = LOG_COLUMNS)`.
- R4: added type hint on `HttpForward.__init__(registry: "ServiceRegistry")` via `TYPE_CHECKING` forward-ref (no runtime import — `from __future__ import annotations` defers evaluation; avoids a circular risk if registry ever imports from services).

**Kept unchanged:**

- R7: field-level inline comments on `ServiceSpec` / `ServiceRequest` / `ServiceResponse` / `ServiceContext` declarations — per user direction, kept even when "obvious" because they're first-definition pedagogy.
- R9: section banner dividers (`# ----- Label -----`) — keep for human auditing.
- Class docstrings using multi-sentence block with no manual line wraps (R1).

### Stage 1.2 — `tests/experiment/services/test_base.py` (closed)

**Applied (2026-04-22):**

- R12: hoisted `from src.experiment.registry import ServiceRegistry` from inside `TestHttpForward._registry()` to the module-top imports block.

**Kept unchanged:**

- Section banners (`# ---- ServiceSpec -----`) — R9.
- Generator / comprehension filters (`all(... for _ in range(50))`) — not targets of R8 per memory.

### Stage 0.2 — `src/io/config.py` (closed)

**Applied (2026-04-22):**

- R1: un-wrapped five hand-wrapped docstring paragraphs (module-top `*IMPORTANT:*` block, `_sub` pedagogy paragraph, `d_bytes` pedagogy paragraph, `NetworkConfig` class pedagogy paragraph, `load_reference` pedagogy paragraph). The linter had already un-wrapped one paragraph (module-level "Resolves...") between turns.
- Dropped 5 WHAT-comments in function bodies that restated the next line: `# walk the variable dict and return the first match` inside `_setpoint`; `# resolve user args into a concrete (profile, scenario) pair`, `# load the raw envelope and pick out its environments block`, `# unpack the per-scenario pieces`, `# resolve each positional slot to a concrete ArtifactSpec` inside `load_profile`.

**Kept unchanged:**

- WHY-comments: precedence markers (`# 1.`, `# 2.`, `# 3.`, `# 4.`) inside `_resolve_source` pair each branch with the docstring's Precedence list; `# reject scenarios that are not declared in the profile` is intent, not restatement; `# sanity-check that routing and node count agree` same.
- Module-top `# TODO: validate row-stochasticity ...` — TODOs are WHY-comments for future work.
- `# forward references + postpone eval type hints` header above `from __future__ import annotations` — explains the purpose of the directive.
- `# adaptation value -> (profile file stem, scenario name within that profile)` section header above `_ADAPTATION_TO_SOURCE`.
- `Attributes:` docstring blocks on `ArtifactSpec` + `NetworkConfig` left intact (see R6/R7 pattern decision flagged below).

**Flagged for user decision (not applied):**

- **R6/R7 pattern conflict.** `ArtifactSpec` (lines 66-156) and `NetworkConfig` (lines 159-204) use `Attributes:` docstring blocks to document fields; `ServiceSpec` / `ServiceContext` in [src/experiment/services/base.py](../src/experiment/services/base.py) use inline comments above each field, no Attributes block. Pick one pattern for the whole codebase: (a) inline comments above every field, drop Attributes blocks; (b) Attributes blocks on every class, no inline comments; (c) both (redundant). Default recommendation until user decides: keep each file in its current pattern — don't drift one to match the other mid-audit. Raise this at the end of the walk, once we've seen how many classes use each pattern.

### Stage 0.2 — `tests/io/test_config.py` (closed)

**Applied (2026-04-22):**

- R12: dropped dead `# native python modules\n# (none)` stub block. If a section has no imports, no need for the section header.

**Kept unchanged:**

- Module-top TODO (`# TODO: extend with a regression case ...`).
- Class docstrings with `**TestClass**` + bullet contracts; per-method `*test_name()*` lead-ins — matches `coding-conventions.md:44` test-doc style.

### Stage 0.3 — `src/experiment/payload.py` (closed)

**Applied (2026-04-22):**

- R1: un-wrapped 2 hand-wrapped docstring paragraphs (`generate_payload` ASCII-alphabet note; `resolve_size_for_kind` request-size-map pedagogy). The linter had already un-wrapped the module docstring + flattened `MockPayload` fields to config.py's pattern between turns.
- R8: rewrote inline ternary `_rng = rng if rng is not None else random.Random()` inside `generate_payload` to an explicit `if rng is None: _rng = random.Random(); else: _rng = rng` block.
- Dropped WHAT-comment `# fallback for unknown kinds` in `resolve_size_for_kind` — the `dict.get(key, default)` idiom is self-documenting.
- User manual-added a one-line inline comment above `MockPayload.kind` documenting the accepted label values (`analyse_request`, `alarm_request`, `drug_request`, `response_default`) — kept per R7 first-definition pedagogy. This is the first exception to the stage 0.2 "no inline field comments when an Attributes block exists" pattern: enum-of-valid-values context that doesn't fit naturally in the Attributes block.

**Kept unchanged:**

- Module-top `# ASCII-only alphabet so one character equals one UTF-8 byte` above `_ALPHABET` — WHY-comment justifying the alphabet choice.
- Inline `# one char equals one UTF-8 byte under the ASCII alphabet` above `_rng.choices(_ALPHABET, ...)` — same WHY, reasserted at the use site for readers who haven't scrolled to the module constant.
- `Attributes:` docstring block on `MockPayload` — matches config.py pattern (set by user's manual edit in stage 0.2).

### Stage 0.3 — `tests/experiment/test_payload.py` (closed)

**Applied (2026-04-22):**

- Added `*test_name()*` lead-in docstrings to all 10 test methods (9 were missing entirely; `test_kind_request_alias` had a docstring but no lead-in). Matches `coding-conventions.md:44` style used elsewhere in the suite (tests/io/test_config.py, tests/experiment/services/test_base.py).

**Kept unchanged:**

- Module docstring + class docstrings already match style.
- Inline `# every character in the ASCII alphabet is 1 byte in UTF-8` in `test_blob_is_exact_byte_size` — WHY-comment justifying the `encode("utf-8")` assertion.

### Stage 0.4 — `src/experiment/registry.py` (closed)

**Applied (2026-04-22):**

- R1: un-wrapped `build_invoke_url` docstring pedagogy paragraph (previously wrapped across 4 lines). User/linter had already un-wrapped the module docstring between turns.
- R8: rewrote inline ternary `_base = base_port_override if base_port_override > 0 else int(method_cfg["base_port"])` inside `from_config` to an explicit `if base_port_override > 0: ...; else: ...` block.
- `RegistryEntry` fields flattened with inline enum-context comments added by user/linter — kept as-is.
- **R3 atomic rename** `filter_names_by_role` → `filter_names_role`. The `by` preposition is not an acronym — violates the verb-first + up-to-5-acronyms rule. Sibling methods (`resolve_base_url`, `build_invoke_url`, `build_healthz_url`) already follow the no-preposition pattern; this one was the outlier. Call sites swept atomically in the same turn: `src/experiment/registry.py` def + module docstring, `tests/experiment/test_registry.py` (9 call sites), `src/scripts/demo_registry.py:70`. Zero external consumers — no launcher / client / notebook hits. Full grep verification post-rename: no matches.
- **R5 + inline-chaining rewrite** of the `filter_names_role` body. The original `return (_n for _n, _e in self.table.items() if _e.role == role)` combined iteration, tuple unpack, and filter predicate into a single generator expression — counts as "inline command chaining" per coding-conventions.md:8. Iterator-short names `_n` / `_e` also mis-applied R5: they look like loop counters but carry real domain meaning (service name, registry entry). Rewritten to an explicit `for _name, _entry in ...: if _entry.role == role: _matching.append(_name); return _matching` body with descriptive locals. First attempt used `yield` (generator function) — reverted after user flagged that `return` on a materialised `List[str]` is more honest, since every caller wraps the result in `list(...)` anyway. Return type tightened `Iterable[str]` → `List[str]` on both `filter_names_role` and the sibling `list_names` (which now calls `list(self.table.keys())` inside); the eager conversion lives in one place instead of at every call site.

**Not touched (user actively editing between turns):**

- `ServiceRegistry` field block (lines 52-57) — linter/user added inline field comments above each field, but the comment on `host: str` currently reads "service name (e.g. `TAS_{1}`, `MAS_{1}`); used as the key for registry lookup and URL resolution" which describes `table`'s keys, not `host`'s value. Likely auto-fill pasted from the wrong Attributes entry. Flag: fix the comment text on `host` (suggested: "host address, usually `127.0.0.1`") or drop all three inline comments and let the `Attributes:` block do the documenting, since the file already has one.

**Kept unchanged:**

- Module-top `# matches \`TAS_{i}\` keys; used to route into the six-in-one Option-B FastAPI app `above`_TAS_KEY_RE` — WHY-comment tying the regex to the architectural choice.

**Deferred (breaking rename, folded into B1):**

- R2: `ServiceRegistry` → `SvcRegistry`. Same blast radius family as the other `Service*` classes. Waits on the B1 experiment-subtree sweep decision.

### Stage 0.4 — `tests/experiment/test_registry.py` (closed)

**Applied (2026-04-22):**

- Added `*test_name()*` lead-in docstrings to all 18 test methods (across `TestFromConfig`, `TestBuildInvokeUrl`, `TestBuildHealthzUrl`, `TestRoleFilters`, `TestTasComponentsShareAPort`, `TestUnknownName`).
- Folded 2 in-body `#` comments into the containing docstrings:
  - `test_filter_names_composite_client`: was `# client-facing composites: ingress (TAS_{1}) + egress (TAS_{5}, TAS_{6})` → now the docstring.
  - `test_filter_names_per_workflow_stage`: was `# each of the three internal-routing composites has exactly one artifact` → now the docstring.
- Rename swept through: 9 call sites of `filter_names_by_role` updated to `filter_names_role` (class docstring line 11, `TestRoleFilters` docstring line 127, and 7 assertion calls).

**Kept unchanged:**

- `_cs01_like_cfg` helper's inline `# six TAS components share port_offset 0 ...` comment on the fixture's dict body — that one IS WHY (explains why all six entries share offset 0), not a test-method pedagogy note.

### Stage 0.5 — `src/dimensional/schema.py` (closed)

**Applied (2026-04-22):**

- Fixed typo on line 29 — `"from\`data/config/method/dimensional.json\`"`was missing a space between "from" and the backtick; now`"from \`data/config/method/dimensional.json\`"`.
- Dropped WHAT-comment `# build the pydasa Schema and run its setup routine` (line 45). The two-line block below it (`Schema(...)` call + `_setup_fdus()` call) reads itself. User/linter also split the `Schema(...)` call across three lines in-flight between turns — kept.

**Kept unchanged:**

- `# guard against silent FDU/framework mismatch before handing off to pydasa` — WHY-comment explaining why the guard exists (catch user-side config errors before PyDASA sees them).
- `# type: ignore[call-arg]` on the `Schema(...)` call — load-bearing type-checker directive for PyDASA's dataclass signature.
- Module + function docstrings already single-line per R1.
- No rename candidates: `build_schema` is verb-first, `fwk` / `fdus` are canonical acronyms from PyDASA.

### Stage 0.5 — `tests/dimensional/test_schema.py` (closed)

**Applied (2026-04-22):**

- Added `*test_name()*` lead-in docstrings to all 7 test methods.
- Rewrote the 2 class docstrings to the `**TestClassName** contract...` style (was `"""Verifies ..."""`; now `"""**TestSchemaConstruction** the Schema carries the TAS T/S/D framework ..."""`).
- R5 prefix consistency: renamed 2 comprehension iterators from `fdu` to `_fdu` (lines 28, 32) to match line 37 and the project-wide "meaningful domain variables carry `_` prefix" rule.
- Folded the in-body `# PyDASA rejects an empty CUSTOM framework; our wrapper propagates.` comment (line 53) into `test_empty_fdu_list_raises`'s new docstring.
- Added missing import-section headers (`# testing framework`, `# pydasa library`, `# module under test`) around the 3 imports, matching the pattern in tests/io/test_config.py and tests/experiment/test_registry.py.

**Kept unchanged:**

- `schema` fixture (referenced by 5 tests) is declared outside this file — likely in `tests/dimensional/conftest.py`; out of scope for this stage. Flag only: ensure fixture name + `_` convention when conftest comes up.

### Stage 0.6 — `src/dimensional/coefficients.py` (closed)

**Applied (2026-04-22):**

- Dropped 4 WHAT-comments inside `derive_coefs` body that restated the next line: `# substitute each placeholder...` (was above the nested `_sub` def), `# apply each spec in declaration order` (above the `for _sp in specs:` loop), `# build the artifact-qualified coefficient symbol` (above the f-string), `# resolve the expression against the actual Pi-keys` (above the `_resolve_expr(...)` call).
- Tightened line 93's mixed WHAT+WHY comment: was `# delegate to pydasa; \`idx=-1\` appends to the coefficient list `(half restates the call, half explains the magic-number); now just the WHY half —`# \`idx=-1\` appends to pydasa's coefficient list rather than overwriting a slot`.

**Kept unchanged:**

- `# placeholder matcher for the \`{pi[i]}\` indices in expr_pattern strings `above`_PI_PAT` (line 35) — WHY-comment anchoring the regex to the spec format.
- `# collect the Pi-group keys in order so expr_pattern indices line up` (line 80) — WHY-comment explaining why order matters.
- Multi-line f-string error message in `_resolve_expr._sub`. Linter re-formatted it between turns to `_msg = f"..." + _msg += "..."` form (was an implicit string-literal concat). Kept as-is; both forms are intentional splits for readability, not R1 violations.
- Fine-grained import section headers (`# text processing` for single `import re`) — intentionally verbose grouping; matches project pattern.

**Deferred:** none. No rename candidates; `derive_coefs`, `_resolve_expr` already verb-first with canonical acronyms.

### Stage 0.6 — `tests/dimensional/test_coefficients.py` (closed)

**Applied (2026-04-22):**

- Added `*test_name()*` lead-in docstrings to all 10 test methods (7 had no docstring at all; 3 had descriptive docstrings missing the lead-in — `test_all_artifacts_get_four_coefficients`, `test_sigma_close_to_unity_after_seed`, `test_phi_collapses_to_L_over_K`).
- Rewrote 3 class docstrings to `**TestClassName** contract...` style: `TestCoefficientDerivation` (was `"""Four named coefficients..."""`), `TestCoefficientValues` (adding the lead-in while preserving its second paragraph about `_std_mean` semantics), `TestExpressionGuardrails` (was `"""Malformed expr_patterns raise clear errors."""`).
- Added import-section headers (`# testing framework`, `# module under test`).

**Kept unchanged:**

- Cross-reference comments inside `TestCoefficientValues` docstring explaining why we read `_std_mean` not `_setpoint` — load-bearing WHY about PyDASA internals.
- The `_std_mean` helper's `*_std_mean()*` lead-in already matched style.
- External fixtures: `engine_ready`, `schema`, `method_cfg`, `dflt_profile`, `tas1_vars` are declared outside this file (in a conftest). Out of scope for this stage; revisit when conftest comes up.

### Stage 0.7 — `src/dimensional/engine.py` (closed)

**Applied (2026-04-22):**

- Dropped 2 WHAT-comments inside `build_engine` body: `# wrap each param dict into a pydasa Variable` (above the dict-comprehension) and `# spin up the engine with the schema and descriptive metadata` (above the `AnalysisEngine(...)` call).
- Collapsed the `description=` argument from a 2-literal concat (`f"..." + "..."`) into one f-string. Between turns, the user/linter additionally swapped the `AnalysisEngine(...)` call from keyword-only (`_idx=idx`, `_fwk=fwk`, ...) to positional form — kept as-is per "file modified" notice.

**Kept unchanged:**

- `# attach variables; pydasa takes ownership from here` — WHY re-asserting the module-docstring invariant at the assignment site (warning future readers that post-assignment mutations to `artifact_vars` will NOT re-sync).
- Module docstring + public-API bullet already match R1.
- No rename candidates: `build_engine` verb-first with canonical acronyms (`schema`, `fwk`, `idx`, `vars`).

### Stage 0.7 — `tests/dimensional/test_engine.py` (closed)

**Applied (2026-04-22):**

- Rewrote 2 class docstrings to `**TestClassName** contract...` style. The `TestPiGroupDerivation` rewrite also replaced its Unicode `→` with plain prose (per R10 adjacent rule against arrows in notebook text; applied to test docstrings for consistency).
- Added `*test_name()*` lead-in docstrings to 9 test methods total (6 were missing entirely; 3 had descriptions missing the lead-in — `test_pi_expressions_stable_across_adaptations`, `test_pi_zero_involves_w_lambda_c`, `test_pi_count_matches_buckingham` had an in-body `#` comment that's now the docstring).
- R10: replaced `→` (Unicode arrow) in `test_pi_expressions_stable_across_adaptations` docstring with ASCII `->`.
- R5 prefix consistency: renamed 6 comprehension iterators `v` -> `_v` (lines 21-33) and 4 iterators `k` -> `_k` (lines 46, 62-67); renamed the local `ans` -> `_ans` (line 69).
- Folded in-body `# 10 relevant variables - 3 FDUs = 7 Pi-groups` (line 44) into `test_pi_count_matches_buckingham`'s new docstring.
- Folded the two short trailing inline comments `# lambda, c, delta` / `# W` (lines 26, 30) into the corresponding test docstrings (they named the expected category members; the test lines are already short enough that the trailing comment was working overtime).
- Added `# module under test` import-section header.

**Kept unchanged:**

- External fixtures `engine_bare`, `engine_ready`, `schema`, `method_cfg`, `dflt_profile`, `opti_profile` — declared in the `tests/dimensional/conftest.py` that will surface at a later stage.

### Stage 0.8 — `src/dimensional/sensitivity.py` (closed)

**Applied (2026-04-22):**

- Dropped 2 WHAT-comments inside `analyse_symbolic` body: `# spin up the pydasa workflow and attach the same variables/coefficients` (above the `SensitivityAnalysis(...)` call) and `# run the symbolic pass at the requested evaluation point` (above the `analyze_symbolic(...)` call). The code below each reads itself.
- Between turns, user/linter additionally swapped `SensitivityAnalysis(...)` from keyword-only to positional args (mirroring stage 0.7's `AnalysisEngine` change) and simplified the `analyze_symbolic(val_type=val_type)` call to positional `analyze_symbolic(val_type)`. Kept.
- **Inline-chaining rewrite (user-flagged)**: the reshape block had a dict-comprehension with filter nested inside a `for` loop — two loops + a filter predicate on one visual layer. Decomposed to: outer `for _coef, _vmap in _raw.items()` builds a local `_numeric: dict[str, float] = {}`; inner `for _var_sym, _val in _vmap.items(): if isinstance(_val, (int, float)): _numeric[_var_sym] = float(_val)`; assign `_out[_coef] = _numeric`. One loop per line, one predicate per line. Names swapped `_v` / `_x` -> `_var_sym` / `_val` to match the naming already used in tests/dimensional/test_sensitivity.py (cross-file R5 consistency).

**Kept unchanged:**

- `# reshape: keep only numeric leaves, drop sympy residues` — WHY-comment explaining why the filter is needed (sympy occasionally returns symbolic residues at degenerate evaluation points; downstream consumers expect pure float).
- Module docstring already matches R1 (single-line per paragraph, including the `*IMPORTANT:*` block about `SEN_{...}` key prefixing).
- No rename candidates: `analyse_symbolic` is British verb-first per R14; kwargs `val_type` / `cat` / `fwk` / `idx` are canonical.

### Stage 0.8 — `tests/dimensional/test_sensitivity.py` (closed)

**Applied (2026-04-22):**

- Rewrote 2 class docstrings to `**TestClassName** contract...` style (`TestSensitivityShape`, `TestSensitivitySigns`).
- Added `*test_name()*` lead-in docstrings to all 9 test methods — 6 sign-tests had only trailing inline math-derivation `#` comments (`# theta = L/K -> d_theta/d_L = 1/K > 0` shape); folded each derivation into the new test docstring.
- R10: swapped 6 Unicode `→` arrows for ASCII `->`. Greek letters (`theta`, `sigma`, `eta`, `phi`, `lambda`, `mu`, `chi`) transcribed to ASCII spelling in the docstrings since they also served as LaTeX-free prose — kept Greek intact only in the actual symbol-key strings (`\\theta_{TAS_{1}}` etc.) which are the engine's keying convention.
- Added `# native python modules` import-section header above `from numbers import Real`.

**Kept unchanged:**

- `sensitivity_results` fixture (referenced by every test) is declared outside this file (in a conftest). Flag only; revisit when conftest comes up.
- Module-level alias constants `_THETA`, `_SIGMA`, `_ETA`, `_PHI` — they hide the `SEN_{...}` PyDASA prefix so the sign-tests stay readable. Module docstring already explains the aliasing rationale.

### Stage 0.9 — `src/dimensional/reshape.py` (closed)

**Applied (2026-04-22):**

- R3 in-file rename: private `_coef_column` -> `_extract_coef_column` (noun-only -> verb-first). Sole internal caller inside `coefs_to_nodes` updated; zero external blast since the function is module-private.
- Dropped 2 WHAT-comments: `# strip the leading backslash and split off the first subscript brace` inside `_extract_coef_column` and `# flatten each derived coefficient to a short column name` inside `coefs_to_nodes`.
- R8: rewrote 6 inline ternaries to explicit `if` / `else` blocks:
  - `coefs_delta`: `_out[_m] = (_o - _d) / _denom if pct else (_o - _d)` split on the `pct` branch (similar rewrite done once earlier in `__post_init__` / `draw_svc_time`).
  - `aggregate_arch_coefs`: 4 denominator-guard ternaries on `_theta_arch`, `_sigma_arch`, `_eta_arch`, `_phi_arch` — each now a 4-line `if <sum> > 0: ...; else: ... = 0.0` block; the degenerate-case branch reads before the normal branch at a glance.
  - `network_delta`: denom guard `abs(_d) if _d != 0 else 1.0` and the pct-branch ternary both split.
- **User-flagged inline-chaining rewrite (lines 124-131 and 355-361)**: both blocks had a multi-line `#` comment followed by a wrapped list-comprehension with a compound `if A and B` predicate. Decomposed both:
  - `coefs_delta`'s `_keys_common` pulls the `set(nds_other[cname])` out to a named `_other_keys` local, then an explicit `for _k in nds_dflt[cname]: if _k in _other_keys: _keys_common.append(_k)` loop.
  - `coefs_delta`'s `_metrics` (lines 129-131 pre-edit) AND `network_delta`'s identical `_metrics` (lines 334-336 pre-edit): compound `if _c in dflt and _c in other` decomposed per R11 into two named booleans `_in_dflt` / `_in_other` combined in a plain `if _in_dflt and _in_other: _metrics.append(_c)`.
- User/linter between turns also reformatted `_fn_lt` dict to multi-line form inside `coefs_to_net` — kept.

**Kept unchanged:**

- `np.where(...)` nested vectorised conditionals in `aggregate_sweep_to_arch` (lines 293-295) — `np.where` is not a Python ternary per R8's vectorised-op exemption; rewriting to a Python loop would hurt performance on the sweep arrays.
- All WHY-comments (declared-order preservation, math-identity derivations like `theta = L/K -> L = theta * K`, PACS-aggregation comments, denominator guards rationale, empty-sweep fallback, uniform-override invariant).
- Module docstring, `Aggregation rules` docstring blocks, `_COEF_NAMES` tuple + its WHY-comment above.

**Deferred to B5 (see Breaking changes pending):**

- R3: `coefs_delta` -> `compute_coefs_delta`.
- R3 + R2: `network_delta` -> `compute_net_delta` (folds in `network -> net` acronym from R2).
- Both touch 03-dimensional.ipynb JSON; batch-swept with other `dimensional/` renames.

### Stage 0.9 — `tests/dimensional/test_reshape.py` (closed)

**Applied (2026-04-22):**

- Rewrote 4 class docstrings to `**TestClassName** contract...` style (`TestNodeShape`, `TestNetworkShape`, `TestDeltaSemantics`, `TestArchitectureAggregation`).
- Added `*test_name()*` lead-in docstrings to all 18 test methods. 9 had no docstring; 9 had descriptions missing the lead-in. Preserved the full explanatory prose on the longer docstrings (`test_aggregate_delta_uses_intersection`, `test_epsilon_uses_cumulative_probability`, etc.) since those explain load-bearing math or the 13-vs-16 node swap semantics.

**Kept unchanged:**

- Module-scoped fixtures `_dim_baseline` / `_dim_aggregate` — already have `*_name()*` lead-ins per style.
- Import-section headers (`# testing framework`, `# modules under test`) already present.

### Stage 1.1 — `src/analytic/queues.py` (closed)

**Applied (2026-04-22):**

- R1: un-wrapped the module-docstring intro paragraph and 9 other hand-wrapped docstring paragraphs (Args/Raises/Returns blocks on `_validate_basic_params`, abstract `calculate_metrics`, `QueueMM1`/`QueueMMs`/`QueueMM1K`/`QueueMMsK` class docstrings, concrete `_validate_params` Raises blocks, the `Queue` factory Args/Raises/Returns, `QueueMMsK.calculate_prob_n` Returns, and the three `calculate_metrics` Side-effects lines across concrete classes).
- R4: added `-> None` return annotation to `BasicQueue.__post_init__`.
- R8: rewrote the inline ternary inside `__str__` (line 191) to a 4-line `if`/`else` block that names `_status_word = "STABLE" | "UNSTABLE"` before the f-string interpolation.
- R11: decomposed the 3-condition compound boolean inside the `Queue` factory (was `if _K_rule == "finite" and _c_rule == "multi" and K_max < c_max:`) into three named locals `_finite`, `_multi`, `_undersized` combined in a single guarded `if _undersized:` branch.
- R12: consolidated 4 import-section banners (`# forward references + postpone eval type hints`, `# data types`, `# abstract base class support`, `# shared math helpers`) into 2 (`# native python modules`, `# local modules`), sorted the stdlib imports alphabetically (abc -> dataclasses -> typing).
- Dropped 9 WHAT-comments across the three concrete `calculate_metrics` methods (variants of `# utilisation and traffic intensity`, `# state-zero probability`, `# block probability and effective arrival rate` that restated the next line).
- Un-wrapped the 3-line hand-wrapped WHY-comment above the final `_cls(...)` call in the `Queue` factory into a single line.

**Kept unchanged:**

- Inline dataclass-field comments on `BasicQueue` (13 fields) — added by user/linter in-flight between turns; matches the R7 first-definition pedagogy pattern. Redundant with the `Attributes:` block in the class docstring but respected per user's pattern direction.
- All math-WHY comments (L = sum formulas, Little's Law references, Erlang-C math, regime-change markers `# rho < 1 regime:` / `# rho == 1 regime:` / `# saturation regime:`, factorial branch comments, `# excess carried by the finite truncation`, `# equivalent to: avg_len - rho * (1 - p_kmax)`).
- `_QUEUE_MODELS` registry comment block (lines ~612-622) — documents the dict shape spec and lists `M/M/s/K` as the alias. Load-bearing WHY.
- `Queue` noun name — Python factory idiom; not an R3 violation.
- `get_metrics` — does work (builds dict), not a trivial getter; stays as method per R13.
- `# TODO:` markers at module top and at end of `Queue` factory.

**Deferred:** none. `gfactorial` rename dropped earlier per user direction.

### Stage 1.1 — `tests/analytic/test_queues.py` (closed)

**Applied (2026-04-22):**

- **B2 test relocation**: moved `TestGFactorial` class (3 methods: `test_zero`, `test_small_int`, `test_half`) out of `tests/analytic/test_queues.py` into the new `tests/utils/test_mathx.py` — matching the `src/` mirror rule (`src/utils/mathx.py` -> `tests/utils/test_mathx.py`). Updated `test_queues.py` module docstring bullet list to drop the `TestGFactorial` entry. Dropped the now-unused `import math` and `from src.utils.mathx import gfactorial` imports. Consolidated imports into 2 sections: `# testing framework` and `# module under test`.

**Kept unchanged:**

- Remaining 3 classes (`TestMM1`, `TestMMcK`, `TestFactoryErrors`) + their 8 test methods — all already have `**TestClassName**` / `*test_name()*` docstrings from prior stages.
- Module-top `# TODO:` extending to M/M/s and M/M/1/K coverage.

### Stage 1.1 — `tests/utils/test_mathx.py` (NEW, closed)

**Created (2026-04-22):**

- New module mirroring `src/utils/mathx.py` per the audit-rule test-layout convention. Hosts the relocated `TestGFactorial` class.
- Module docstring + class docstring + per-method `*test_name()*` lead-ins in place.
- Import-section headers (`# native python modules`, `# testing framework`, `# module under test`).
- Also created empty `tests/utils/__init__.py` so the package is importable.

**B2 closed** — the test-mirror gap flagged from stage 0.1 is resolved.

## Breaking changes pending

Logged as they surface; each entry specifies name, line, and every call-site module that must swap before the rename commit lands.

### B1 — R2 acronym renames across `src/experiment/` subtree

Reason to batch: seven related renames across one subtree all propagate to the same upstream modules. Doing them as one sweep (per the CLAUDE.md "3-step atomic rename" rule) avoids repeated touches of each call site.

| Old name                                        | New name        | Source of truth    | Call-site modules to sweep                                                                                                                                                                                                                                                                                         |
| ----------------------------------------------- | --------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ServiceSpec`                                 | `SvcSpec`     | `base.py:37`     | `services.atomic`, `services.composite`, `services.instruments`, `services.__init__`, `experiment.client`, `experiment.instances.tas`, `experiment.instances.third_party`, `experiment.instances.__init__`, `experiment.launcher`, `methods.experiment`, demos, all `tests/experiment/**`    |
| `ServiceRequest`                              | `SvcReq`      | `base.py:107`    | same set as above                                                                                                                                                                                                                                                                                                  |
| `ServiceResponse`                             | `SvcResp`     | `base.py:123`    | same set as above                                                                                                                                                                                                                                                                                                  |
| `ServiceContext`                              | `SvcCtx`      | `base.py:158`    | same set as above                                                                                                                                                                                                                                                                                                  |
| `ExternalForwardFn`                           | `ExtFwdFn`    | `base.py:252`    | `services.atomic`, `services.composite`, `services.__init__`, `experiment.instances.tas`, `experiment.instances.third_party`                                                                                                                                                                             |
| `ServiceRegistry`                             | `SvcRegistry` | `registry.py:43` | `experiment.client`, `experiment.launcher`, `experiment.services.base` (TYPE_CHECKING forward-ref), `tests/experiment/test_registry.py`, `tests/experiment/services/test_base.py`, `demo_registry`, `demo_client`                                                                                    |
| field `service_name` (on `ServiceResponse`) | `svc_name`    | `base.py:130`    | every module that reads `resp.service_name` or writes `{"service_name": ...}` — grep confirms: `services.instruments`, `services.atomic`, `services.composite`, tests, `LOG_COLUMNS` (wire schema — breaking for on-disk CSVs: decide whether to change or keep for backward compat with prior runs) |
| field `message` (on `ServiceResponse`)      | `msg`         | `base.py:136`    | wire schema; touches every producer/consumer of the body                                                                                                                                                                                                                                                           |
| arg `service_name` (on `derive_seed`)       | `svc_name`    | `base.py:80`     | `experiment.launcher:125`                                                                                                                                                                                                                                                                                        |

**Decision pending before B1 runs:**

- Whether to include the wire-schema field renames (`service_name`, `message`) in B1 or defer them. They would be breaking for existing on-disk CSVs in `data/results/experiment/...`. Recommendation: rename in code AND run migrations on existing CSVs, OR keep the wire field names as-is and only rename the class/alias names. Needs user call.

### B3 — R2 acronym renames across `src/io/` (surface from stage 0.2)

Flagged from stage 0.2 audit of config.py. Like B1, this is a coordinated multi-file sweep — the target symbols are public and heavily imported.

| Old name               | New name            | Source of truth   | Call-site modules to sweep                                                                                                                                                                                                  |
| ---------------------- | ------------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `load_method_config` | `load_method_cfg` | `config.py:337` | `methods/analytic.py`, `methods/stochastic.py`, `methods/dimensional.py`, `methods/experiment.py`, `demo_payload.py`, `demo_registry.py`, `demo_client.py`, `experiment.launcher`, all `tests/methods/**` |
| `NetworkConfig`      | `NetCfg`          | `config.py:160` | `analytic.jackson`, `stochastic.simulation`, `dimensional.networks`, `experiment.launcher`, every `methods/*.py`, every `tests/methods/*.py`, every consumer test                                               |

Very high blast radius — defer until we decide a batch window where the whole tree can be swept atomically (same argument as B1).

### B4 — Private-method verb-first rename on `ArtifactSpec`

Surface from stage 0.2. Low blast radius, all internal to one class — can be done in-file at the stage's closure.

| Old name                   | New name                                                        | Why                                                  |
| -------------------------- | --------------------------------------------------------------- | ---------------------------------------------------- |
| `ArtifactSpec._setpoint` | `ArtifactSpec.read_setpoint` or `ArtifactSpec.get_setpoint` | R3: noun-only method name should be verb-first       |
| `ArtifactSpec._sub`      | `ArtifactSpec.format_sub`                                     | R3: noun-only; the method formats the subscript form |

Callers: the 6 `@property` getters on the same class (`mu`, `c`, `K`, `epsilon`, `d_kb`, `d_bytes`) call `self._setpoint(...)` and `self._sub()`. Not exposed outside the class. Decide at the B1/B3 batch window along with other renames.

### B5 — R2 + R3 acronym + verb-first renames on `src/dimensional/reshape.py` public API

Flagged from stage 0.9. Small blast radius (4 files each) but one is [03-dimensional.ipynb](../03-dimensional.ipynb) JSON — notebook edits are fragile. Deferred to a coordinated sweep so the notebook rewrite happens once.

| Old name          | New name                | Reason                               | Call-site modules to sweep                                                                                                                                               |
| ----------------- | ----------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `coefs_delta`   | `compute_coefs_delta` | R3 noun-only -> verb-first           | `src/dimensional/__init__.py` (re-export + `__all__`), `tests/dimensional/test_reshape.py` (4 hits), `03-dimensional.ipynb` (2 hits), module docstring reference |
| `network_delta` | `compute_net_delta`   | R3 noun-only + R2 `network -> net` | `src/dimensional/__init__.py` (re-export + `__all__`), `tests/dimensional/test_reshape.py` (3 hits), `03-dimensional.ipynb` (2 hits), module docstring reference |

**Kept as-is (`to_*` idiom, not a violation):** `coefs_to_nodes`, `coefs_to_net`. Python convention (mirrors `MockPayload.to_dict`, `dict.to_list`, `pandas.DataFrame.to_dict` etc.) — reads as "convert X to Y" with an implicit verb.

### B12 — R3 private renames on `src/experiment/launcher.py`

Flagged from stage 8.1. All private helpers with noun-first names.

| Old name | New name | Reason | Call-site modules |
|---|---|---|---|
| `_avg_request_size` | `_compute_avg_req_size` | R3 noun -> verb + R2 `request -> req` | in-file internal caller (`__aenter__`) |
| `_specs_from_config` | `_build_specs_from_cfg` | R3 noun-phrase -> verb-first + R2 `config -> cfg` | in-file + `tests/experiment/test_launcher.py` (if imported directly — check) |
| `_routing_row` | `_read_routing_row` | R3 noun -> verb | in-file internal callers (2 sites) |
| `_router_kind_map` | `_build_router_kind_map` | R3 noun -> verb | in-file internal caller |
| `lambda_z_entry` (public method) | `get_lam_z_entry` | R3 noun -> verb + R2 `lambda -> lam` | `methods/experiment.py` (caller), `tests/experiment/test_launcher.py` (2 hits), `tests/methods/test_experiment.py` (likely) |

### B11 — R2 renames on `src/experiment/client.py` public API

Flagged from stage 6.1. `ClientConfig` is consumed by `methods.experiment`; `RampConfig` / `CascadeConfig` are nested inside it. Wide blast.

| Old name | New name | Reason | Call-site modules to sweep |
|---|---|---|---|
| `ClientConfig` | `ClientCfg` | R2 `configuration -> cfg` | `src/methods/experiment.py`, `tests/experiment/test_client.py` (lots), `src/scripts/demo_client.py`, `tests/methods/test_experiment.py` |
| `RampConfig` | `RampCfg` | R2 `configuration -> cfg` | same call-site set (nested inside ClientConfig) |
| `CascadeConfig` | `CascadeCfg` | R2 `configuration -> cfg` | same call-site set |
| field `entry_service` | `entry_svc` | R2 `service -> svc` | internal + notebook `05-experiment.ipynb` if referenced |
| field `request_size_bytes` | `req_size_bytes` | R2 `request -> req` | internal + method config JSON; coordinated with the `request_sizes_by_kind` JSON key rename (would also touch `data/config/method/experiment.json`) |
| field `request_sizes_by_kind` | `req_sizes_by_kind` | R2 `request -> req` | same — JSON config file needs the key renamed too |

### B10 — R2 + R3 renames on `src/dimensional/networks.py` public API

Flagged from stage 3.3. Broad blast — these power the yoly notebook.

| Old name | New name | Reason | Call-site modules to sweep |
|---|---|---|---|
| `sweep_architecture` | `sweep_arch` | R2 `architecture -> arch` | `src/dimensional/__init__.py` re-export + `__all__`, `src/methods/dimensional.py`, `tests/dimensional/test_networks.py` (3 hits), notebook `04-yoly.ipynb` |
| `_find_max_stable_lambda_factor` | `_find_max_stable_lam_factor` | R2 `lambda -> lam` (private, in-file + test) | `src/dimensional/networks.py` (1 internal caller), `tests/dimensional/test_networks.py` (imports it directly) |
| `_setpoint` (on `networks.py`) | `read_setpoint` | R3 noun-only private -> verb-first; same candidate as stage 0.2's `ArtifactSpec._setpoint` (B4) — coordinate renames so the verb form is identical across both files | `src/dimensional/networks.py` internal caller, `tests/dimensional/test_networks.py` (imports + 2 uses) |

### B9 — R2 renames on `src/analytic/metrics.py` public API

Flagged from stage 3.2. Wide blast radius — both functions are re-exported from `src/analytic/__init__.py` and imported by every method module.

| Old name | New name | Reason | Call-site modules to sweep |
|---|---|---|---|
| `aggregate_network` | `aggregate_net` | R2 `network -> net` | `src/analytic/__init__.py` re-export, `src/methods/analytic.py`, `src/methods/stochastic.py`, `src/methods/experiment.py`, `src/dimensional/reshape.py` (if cross-referenced), `tests/analytic/test_metrics.py` (imports it), potentially notebooks `01-analytic.ipynb`, `02-stochastic.ipynb`, `05-experiment.ipynb` |
| `check_requirements` | `check_reqs` | R2 `requirements -> reqs` | `src/analytic/__init__.py` re-export, all `src/methods/*.py`, `tests/analytic/test_metrics.py`, notebooks |

### B8 — R2 `service -> svc` on the `mount_*_service` API

Flagged from stage 3.1 re-check. The acronym table mandates `service -> svc` in every position; both `mount_atomic_service` and `mount_composite_service` carry the un-shortened form.

| Old name | New name | Source | Call-site modules to sweep |
|---|---|---|---|
| `mount_atomic_service` | `mount_atomic_svc` | `src/experiment/services/atomic.py` | `src/experiment/services/__init__.py` re-export, `tests/experiment/services/test_atomic.py` (3 hits), `src/experiment/instances/third_party.py`, potentially `src/experiment/instances/tas.py`, demos |
| `mount_composite_service` | `mount_composite_svc` | `src/experiment/services/composite.py` | to be confirmed when stage 4.1 opens; follows the same blast pattern |

Batch with B1 (the other `Service*` class renames) so the whole `experiment/services/` public surface flips in one sweep.

### B7 — R2 + R3 renames on `src/stochastic/simulation.py` public API

Flagged from stage 2.3. Mixed blast — public `simulate_network` / `solve_network` names are widely referenced. Batched with other renames.

| Old name | New name | Reason | Call-site modules to sweep |
|---|---|---|---|
| `simulate_network` | `simulate_net` | R2 `network -> net` | `src/stochastic/__init__.py`, `tests/stochastic/test_simulation.py`, `src/stochastic/simulation.py` (self-reference in `solve_network`), plus module docstring + `*test_name()*` lead-ins |
| `solve_network` | `solve_net` | R2 `network -> net`; also clashes with `src.analytic.jackson.solve_network` intentionally (same-shape API) so the rename must be coordinated with B6 or both kept parallel | `src/stochastic/__init__.py`, `src/methods/stochastic.py`, potentially notebook `02-stochastic.ipynb` |
| `lambda_zero` (param on `simulate_network`) | `lam_z` | R2 acronym (aligned with B6's same rename on `solve_jackson_lambdas`) | call-site uses keyword; safe in-signature + docstring + test kwarg |
| `_time_weighted_mean` | `compute_time_weighted_mean` | R3 noun-only private -> verb-first | in-file, `_summarise_replication` caller |
| `_model_string` | `format_model_string` | R3 noun-only private -> verb-first | in-file + `tests/stochastic/test_simulation.py` (imports `_model_string` directly) |

### B6 — R2 + R3 renames on `src/analytic/jackson.py` public API

Flagged from stage 2.1. Mixed blast radius — mostly in-house but `solve_jackson_lambdas` is used by `dimensional.networks` too. Batched with other renames.

| Old name | New name | Reason | Call-site modules to sweep |
|---|---|---|---|
| `solve_jackson_lambdas` | `solve_jackson_lams` | R2 `lambda -> lam` acronym | `src/analytic/__init__.py`, `src/dimensional/networks.py`, `src/analytic/jackson.py` (internal callers in `per_artifact_lambdas`), `tests/analytic/test_jackson.py` |
| `per_artifact_lambdas` | `compute_lams_per_artifact` | R2 (`lambdas -> lams`) + R3 (noun-only -> verb-first) | `src/analytic/jackson.py` (internal callers), `tests/analytic/test_jackson.py` (likely only) — zero external imports |
| `per_artifact_rhos` | `compute_rhos_per_artifact` | R3 noun-only -> verb-first | `src/analytic/jackson.py` (internal callers: `lambda_z_for_rho`), `tests/analytic/test_jackson.py` |
| `lambda_z_for_rho` | `invert_rho_to_lam_z` | R2 + R3 noun-phrase -> verb-first | `src/analytic/jackson.py` (internal), `src/methods/experiment.py` (FR-3.5 caller in rho-grid path), `tests/analytic/test_jackson.py` |
| `lambda_zero` (param on `solve_jackson_lambdas`) | `lam_z` | R2 acronym | call-site uses positional, safe rename in-signature + docstring |

### B2 — Stage 1.1 test relocation (closed 2026-04-22)

- `gfactorial` naming: **kept as-is per user direction**. Math-primitive idiom that parallels `math.factorial` / `math.gamma` carries more weight than verb-first naming for this one symbol. Not rolled back, not flagged for future rename.
- Test-mirror gap: **resolved in stage 1.1**. `TestGFactorial` moved from `tests/analytic/test_queues.py` to the new `tests/utils/test_mathx.py` (mirror of `src/utils/mathx.py`). New `tests/utils/__init__.py` created.

## 2026-04-22 follow-up — restored tag-the-step WHAT-comments across earlier stages

**User feedback:** "some are obvious but some are important" — the WHAT-comment drops in stages 0.2 / 0.6 / 0.7 / 0.8 / 0.9 / 1.1 / 2.1 were too aggressive. Revised policy: tag-the-math-quantity / label-the-pipeline-step comments are KEPT even when they read like WHAT at first glance, because they help readers unfamiliar with the domain navigate multi-line computations.

**Restored:**
- `src/io/config.py`: `# walk the variable dict and return the first match` (in `_setpoint`), 4 pipeline-step tags in `load_profile` (`# resolve user args into a concrete (profile, scenario) pair`, `# load the raw envelope and pick out its environments block`, `# unpack the per-scenario pieces`, `# resolve each positional slot to a concrete ArtifactSpec`).
- `src/dimensional/coefficients.py`: 3 tags in `derive_coefs` (`# apply each spec in declaration order`, `# build the artifact-qualified coefficient symbol`, `# resolve the expression against the actual Pi-keys`).
- `src/dimensional/engine.py`: `# wrap each param dict into a pydasa Variable`, `# spin up the engine with the schema and descriptive metadata`.
- `src/dimensional/sensitivity.py`: `# spin up the pydasa workflow and attach the same variables/coefficients`, `# run the symbolic pass at the requested evaluation point`.
- `src/dimensional/reshape.py`: `# strip the leading backslash and split off the first subscript brace`, `# flatten each derived coefficient to a short column name`.
- `src/analytic/queues.py`: restored `# utilisation and traffic intensity`, `# state-zero probability` pairs across the four `calculate_metrics` methods + `# block probability and effective arrival rate` on the two finite-K variants.
- `src/analytic/jackson.py`: `# coerce inputs to float arrays (accept lists too)`, `# build the identity of matching shape and solve the linear system` (in `solve_jackson_lambdas`); `# accumulators for per-node rows and any unstable nodes found`, `# build the queue with the Jackson-solved arrival rate`, `# track nodes that come out unstable (rho >= 1)`, `# record the per-node row for the output DataFrame` (in `solve_network`).

**Kept dropped (truly redundant WHAT with zero added context):**
- `src/experiment/payload.py`: `# fallback for unknown kinds` above `return int(sizes_by_kind.get("response_default", default))` — the `dict.get(key, default)` idiom is self-documenting.
- `src/dimensional/coefficients.py`: `# substitute each placeholder or raise if the index is out of range` — the `if _i >= len: raise; return pi_keys[_i]` body plus the `Raises:` docstring entry is unambiguous.

**Refined rule added (informal R-checklist addendum, applied going forward):**
> Pipeline-step or math-quantity labels above multi-line blocks count as WHY-comments, not WHAT. The test: if removing the comment makes a reader unfamiliar with the domain parse more code to know what the next block *is*, keep it.

## Ready-to-start

Stage 1.3: [src/view/dc_charts.py](../src/view/dc_charts.py) + [tests/view/test_dc_charts.py](../tests/view/test_dc_charts.py) — depends on the deferred `view.qn_diagram` for 3 private helpers (`_TEXT_BLACK`, `_generate_color_map`, `_save_figure`). Can audit the non-dependent parts now and re-check when `qn_diagram` opens. Alternatively, jump to Stage 2.2 [src/experiment/services/instruments.py](../src/experiment/services/instruments.py) (deps on already-closed `services.base`).

## Deferred components

### `src/view/qn_diagram.py` (stage 0.10)

**Reason for deferral:** largest file under `src/view/` and predominantly UI/plotting concerns (matplotlib rcParams, networkx edge-layout, SVG-fill quirks, palette selection). These concerns are orthogonal to the rest of the audit rules — once we've closed everything upstream, the view module can be audited as one big standalone sweep with the plotter-patterns memory ([project_plot_view_patterns.md](../../../../../Users/Felipe/.claude/projects/c--Users-Felipe-OneDrive-Documents-GitHub-DASA-Design-PyDASA-CS1-TAS/memory/project_plot_view_patterns.md)) as the canonical reference. Downstream consumers (`view.dc_charts`, `view.__init__`, every method notebook) still get audited on their own stages; they just reference whatever `qn_diagram` exports today without us touching it mid-walk.

### Terminology sweep — increase / decrease vs improvement / degradation (R15)

**Reason for deferral:** the `improvement` / `degradation` pair is value-laden and assumes a goal direction that DASA's dimensional coefficients don't prescribe. Replace every occurrence with the neutral directional pair `increase` / `decrease` (or contextually: `rise` / `fall`, `up` / `down`). Applies to src, tests, docstrings, notebook markdown, `notes/*.md`, and any `__OLD__/` reference prose we port forward. Batch-execute after B1-B5 so all renames land together.

**Repo-wide scan, 2026-04-22:** only one `src/` file contains the terms, and it's already deferred:

| File                            | Lines             | Hits to rewrite                                                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/view/qn_diagram.py`      | 78-79             | `_BAR_GREEN = "#4CAF50"   # improvement` -> `# decrease`; `_BAR_RED = "#FF5252"     # degradation` -> `# increase`. Note the color mapping: green means the metric decreased and red means it increased — neutrally described, no goal direction.                                                                                                                                                         |
| `src/view/qn_diagram.py`      | 1234              | `plot_net_delta` docstring — "negative deltas (the metric decreased) are drawn green (improvement) and positive deltas are drawn red (degradation)" -> rewrite to "negative deltas (the metric decreased) are drawn green and positive deltas (the metric increased) are drawn red. Interpretation is left to the caller; `total_throughput` flips colour convention only when callers want 'more is green'." |
| `src/view/qn_diagram.py`      | 1256-1257         | inline `# negative delta ... -> improvement -> green; positive delta -> degradation -> red` -> neutral phrasing.                                                                                                                                                                                                                                                                                                 |
| `src/view/qn_diagram.py`      | 1288, 1290        | legend labels `"Improvement"` / `"Degradation"` -> `"Decrease"` / `"Increase"`.                                                                                                                                                                                                                                                                                                                            |
| `tests/`, `src/` (non-view) | —                | clean.                                                                                                                                                                                                                                                                                                                                                                                                             |
| `notes/context.md`            | 48, 214, 467, 768 | "improve reliability" prose + paper-title citation ("Applying Dimensionless Analysis to Improve..."). Citation title preserved verbatim; surrounding prose rewritten when notes are swept.                                                                                                                                                                                                                         |
| `notes/objective.md`          | 71, 79            | case-study narrative prose; rewritten during notes sweep.                                                                                                                                                                                                                                                                                                                                                          |

Every in-source site is inside `qn_diagram.py`, so the R15 swap collapses into stage 0.10's one big UI/plotting audit. No earlier stage forces the swap.

**R15 sweep executed 2026-04-22** (stage 0.10 close):
- `_BAR_GREEN = "#4CAF50"` (improvement semantic) -> `_BAR_BLUE = "#427ABE"` (decrease, pastel blue)
- `_BAR_RED = "#FF5252"` (degradation semantic) -> `_BAR_ORANGE = "#FFB380"` (increase, pastel orange)
- `plot_net_delta` docstring rewritten: colouring is now documented as "neutral and sign-only"; the stale `total_throughput` flip-rule claim (which the code never implemented) was removed.
- Inline sign-rule comment rewritten from `# negative -> improvement -> green; positive -> degradation -> red` to `# negative -> decrease -> pastel blue; positive -> increase -> pastel orange`; explicit `for` loop replaces the inline ternary (also closes R8).
- Legend labels `Improvement` / `Degradation` -> `Decrease` / `Increase`.
- `plot_nd_ci` updated: stochastic-mean error bars now use `_BAR_BLUE`; analytic-reference overlay uses `_BAR_ORANGE`. No semantic-direction claim in that plot; the colours are just contrast accents.
- `notes/context.md` + `notes/objective.md` prose still contain `improve` / legacy phrasing; paper-title citation preserved verbatim. Rewriting the surrounding prose is a notes-sweep task, not a src audit task.

## 2026-04-22 follow-up — keyword-args regression (stages 0.7, 0.8, 9.3)

**Bug introduced during stages 0.7 + 0.8:** linter/user swapped `AnalysisEngine(...)` and `SensitivityAnalysis(...)` calls from keyword-only to positional form. The pydasa dataclass field order walks MRO (SymBasis `_sym, _fwk, _alias` → IdxBasis `_idx` → Foundation `_name, description` → WorkflowBase `_variables, _schema, _coefficients, _results, _is_solved`), so positional `AnalysisEngine(idx, fwk, schema, name, description)` landed `idx` into `_sym`, `schema` into `_alias`, leaving `_schema` at its default `None`. pydasa then hit the CUSTOM-framework guard and raised `ValueError: Custom framework requires '_fdu_lt' to define FDUs`. 6 failures + 62 errors across `tests/dimensional/**` + `tests/methods/test_dimensional.py`.

**Reverted:**
- `src/dimensional/engine.py:47-51` — `AnalysisEngine(...)` back to keyword form (`_idx=idx, _fwk=fwk, _schema=schema, _name=..., description=...`); inline comment pinned explaining why positional doesn't work.
- `src/dimensional/sensitivity.py:47-51` — `SensitivityAnalysis(...)` back to keyword form; same pinned comment. `analyze_symbolic(val_type)` also switched to `analyze_symbolic(val_type=val_type)` for consistency.

**Related R4 tightening (stage 9.3 re-touch):** tightened `_analyse_artifact(artifact: Any, schema: Any, ...)` to `_analyse_artifact(artifact: ArtifactSpec, schema: Schema, ...)`. `ArtifactSpec` added to `src/io/__init__.py` `__all__` to support the annotation. `Schema` imported from `pydasa.dimensional.vaschy` directly.

**Verification:** `tests/dimensional/` 66 passed, `tests/methods/test_dimensional.py` 22 passed. Stage 0.7, 0.8, 9.3 remain closed; no other file touched.

## 2026-04-22 follow-up — B-batch partial execution (B4, B6-partial, B12)

Executed the safe subset of the 11 deferred B-batch renames: those with low blast radius and no notebook / wire-schema / JSON-config touch. The remaining high-blast batches (B1, B3, B5, B7, B8, B9, B10, B11) stay deferred pending user decision on wire-schema vs backward-compat CSV and notebook-edit scheduling.

**B4 executed** (ArtifactSpec internal renames) — `src/io/config.py`:
- `ArtifactSpec._setpoint` → `ArtifactSpec.read_setpoint` (R3 noun-only → verb-first).
- `ArtifactSpec._sub` → `ArtifactSpec.format_sub` (R3 noun-only → verb-first).
- Call sites swept: 5 `@property` getters in `config.py` (mu, c, K, epsilon, d_kb), `src/methods/analytic.py:67`. No tests referenced either method directly.

**B6 partial executed** (analytic.jackson public renames without notebook touch) — `src/analytic/jackson.py`:
- `per_artifact_lambdas` → `compute_lams_per_artifact` (R2 `lambdas → lams` + R3 noun → verb).
- `per_artifact_rhos` → `compute_rhos_per_artifact` (R3 noun → verb).
- `lambda_z_for_rho` → `invert_rho_to_lam_z` (R2 + R3 noun-phrase → verb-first).
- Call sites: module docstring, 10 in-file references, `tests/analytic/test_jackson.py` (14 hits + import reordered alphabetically).
- Not re-exported from `src/analytic/__init__.py`, no methods/ consumers — blast radius stayed within the one src + one test file.
- **Still deferred from B6:** `solve_jackson_lambdas` → `solve_jackson_lams` and `lambda_zero` → `lam_z` param rename (both affect `src/dimensional/networks.py` and notebook `01-analytic.ipynb` directly).

**B12 executed** (launcher private helpers + `lambda_z_entry` public method) — `src/experiment/launcher.py`:
- `_avg_request_size` → `_compute_avg_req_size` (R3 noun → verb + R2 `request → req`).
- `_specs_from_config` → `_build_specs_from_cfg` (R3 + R2 `config → cfg`).
- `_routing_row` → `_read_routing_row` (R3 noun → verb).
- `_router_kind_map` → `_build_router_kind_map` (R3 noun → verb).
- `lambda_z_entry` → `get_lam_z_entry` (R3 + R2 `lambda → lam`).
- Call sites: 3 internal in launcher.py + `tests/experiment/test_launcher.py` (2 hits) + `tests/experiment/test_mem_budget.py` (5 hits for `_compute_avg_req_size`). No notebook reference found.

**Still deferred** (blast touches at least one notebook, JSON config, or wire-schema CSV — needs user call on scheduling + compat strategy):

| Batch | Why deferred |
|---|---|
| B1 | `Service*` class renames + wire-schema field `service_name`/`message` decision on on-disk CSVs |
| B3 | `NetworkConfig` / `load_method_config` blast across every method + notebook + demo |
| B5 | `coefs_delta` / `network_delta` hits `03-dimensional.ipynb` |
| B6 remainder | `solve_jackson_lambdas` hits `dimensional.networks` + notebooks |
| B7 | `simulate_network` / `solve_network` hits `02-stochastic.ipynb` + coordination with B6 |
| B8 | `mount_*_service` must batch with B1's `Service*` renames |
| B9 | `aggregate_network` / `check_requirements` hit every notebook |
| B10 | `sweep_architecture` hits `04-yoly.ipynb` |
| B11 | `ClientConfig` / `request_sizes_by_kind` key rename needs `data/config/method/experiment.json` key renamed in lockstep |

## 2026-04-22 follow-up — R15 notes terminology sweep

Applied the neutral directional rewording to `notes/context.md` + `notes/objective.md`. Citation titles preserved verbatim (they are third-party paper names).

**Rewrites:**
- `context.md:48`: "signals ... degrade whenever the register loses freshness" → "signals ... fall whenever the register loses freshness".
- `context.md:214` (PACS table row): "reduce contention and improve reliability" → "reduce contention and raise reliability".
- `context.md:467`: "both degrade whenever a gateway falls behind" → "both fall ...".
- `context.md:467`: "more frequent synchronisation improves register freshness" → "raises register freshness".
- `objective.md:71`: "*Retry* and *Select Reliable* both improve *Reliability*" → "both raise *Reliability*".
- `objective.md:79`: "more frequent synchronisation improves freshness" → "raises freshness".
- `objective.md:79`: "a stale register degrades both" → "a stale register lowers both".

**Preserved verbatim (third-party citation titles):**
- `context.md:768`: "*Applying Dimensionless Analysis to Improve Attribute-Driven Design in Self-Adaptable Software Solutions*" (Arteaga Martin / Correal Torres, 2023).

**Not rewritten (legitimate non-value-laden uses):** none left after sweep — every bare "improve"/"degrade" in prose was either reworded or is inside a paper title.

## 2026-04-22 follow-up — `plot_dim_topology` added (Stage 0.10 + Stage 9.3 follow-through)

User flagged that `data/img/dimensional/` was not aligned with `data/img/analytic/`: analytic baseline has `topology.{png,svg}` while dimensional baseline only had `nd_heatmap.{png,svg}`, and the non-baseline dimensional folders had 3 figures vs analytic's 5. Added a new plotter to close the gap.

**New plotter:** `plot_dim_topology(rout, nds, *, color_by="theta", glossary, nd_names, title, file_path, fname, verbose)` in [src/view/qn_diagram.py](../src/view/qn_diagram.py). Mirrors `plot_qn_topology` layout (3/4 graph + 1/4 table, same BFS layout, same edge style) but swaps semantics:
- Node colouring by `nds[color_by]` (default `theta`; same `coolwarm` cmap as the QN view for visual consistency).
- Per-node labels show every present coefficient among `theta`, `sigma`, `eta`, `phi` (key line + one mathtext line per coefficient).
- Per-node table below the graph has `Component` + one column per coefficient.
- New `DIM_GLOSSARY_DEFAULT` constant documents the four dimensionless groups; overridable via `glossary=...`.
- Two shared private helpers added (`_draw_dim_topology_axis`, `_add_dim_node_table`) so future sibling plotters (e.g. `plot_dim_topology_grid`) can reuse the styling.

**Exports:** `plot_dim_topology` + `DIM_GLOSSARY_DEFAULT` added to `src/view/__init__.py` `__all__`, kept alphabetically sorted.

**`plot_nd_heatmap` kept intact** per user direction — the function still exists and the notebook still calls it so `data/img/dimensional/baseline/nd_heatmap.{png,svg}` continues to regenerate.

**Notebook `03-dimensional.ipynb` patched:**
- Added `plot_dim_topology` to the imports cell.
- Inserted a new section "4. Dimensionless topology (per adaptation)" that loops `_ADAPTATIONS` and writes `topology.png` to `data/img/dimensional/<adp>/` for every adaptation.
- Renumbered sections 4 → 5, 5 → 6, 6 → 7, 7 → 8, 8 → 9 (old nd_heatmap section is now 5, etc.).

**File layout after re-execution (matches analytic parity):**
- `baseline/`: `topology.{png,svg}` + `nd_heatmap.{png,svg}` (kept).
- `s1/`, `s2/`, `aggregate/`: `topology.{png,svg}`, `nd_diffmap_vs_baseline.{png,svg}`, `net_delta_vs_baseline.{png,svg}` (+ `net_bars_all.{png,svg}` in `aggregate/` only).

**Rule-check on the new plotter (R1–R15 spot-check):** keyword-only after `*,`, returns `Figure`, `_TEXT_BLACK` for text, mathtext-wrapped LaTeX labels, `#010101` not `"black"`, `arc3,rad=0.2` uniform edge style, PNG + SVG save via `_save_figure`, British English ("Dimensionless Topology", "Occupancy"). No inline ternaries. Docstring single-line per bullet. Verb-first name. All compliant.

**Module-docstring counter updated** to "Eight plotters" (previously "Seven") with the new entry inserted in the bullet list between `plot_qn_topology_grid` and `plot_nd_heatmap`.

## 2026-04-22 follow-up — full B-batch execution (B3, B1+B8, B5, B6 remainder, B7, B9, B10, B11)

Drained every remaining B-batch in one sweep. Each rename was applied whole-word via regex across `src/`, `tests/`, demo scripts, and every notebook (skipping `notes/audit.md` and `notes/devlog.md` which are historical records). On-disk JSON **file names**, **Variable-dict JSON keys** (`_setpoint`, `_mean`, `_data`, ...), and **wire-schema CSV column names** (`service_name`, `message`) were deliberately NOT touched — only Python identifiers flipped.

### B3 — `NetworkConfig → NetCfg`, `load_method_config → load_method_cfg`

27 files touched: all `src/methods/*.py`, `src/io/{config,__init__}.py`, `src/analytic/jackson.py`, `src/dimensional/{networks,reshape}.py`, `src/experiment/launcher.py`, `src/stochastic/{simulation,__init__}.py`, every demo, every test under `tests/experiment/` and `tests/methods/`, and all six notebooks (01-analytic, 02-stochastic, 03-dimensional, 04-yoly, 05-experiment, 06-comparison).

### B1 + B8 — `Service* / ExternalForwardFn / ServiceRegistry / mount_*_service → Svc* / ExtFwdFn / SvcRegistry / mount_*_svc`

28 files touched: entire `src/experiment/` subtree (services, instances, registry, launcher, client, payload), every `demo_*.py`, every `tests/experiment/**`. **Wire-schema fields `service_name` and `message` on `SvcResp` were NOT renamed** — they are CSV column names persisted in `data/results/experiment/.../log.csv`; renaming them would break every historical replication dump. The class-name renames are internal (Python identifiers only); the CSV schema stays intact.

### B5 — `coefs_delta → compute_coefs_delta`, `network_delta → compute_net_delta`

4 files: `src/dimensional/reshape.py` + `__init__`, `tests/dimensional/test_reshape.py`, `03-dimensional.ipynb`.

### B6 remainder — `solve_jackson_lambdas → solve_jackson_lams`, param `lambda_zero → lam_z`

7 files: `src/analytic/{jackson,__init__}.py`, `src/dimensional/networks.py`, `src/stochastic/simulation.py`, `tests/analytic/test_jackson.py`, `tests/dimensional/test_networks.py`, `tests/stochastic/test_simulation.py`. No notebook references.

### B7 — `simulate_network → simulate_net`, stochastic `solve_network → solve_net`, `_time_weighted_mean → compute_time_weighted_mean`, `_model_string → format_model_string`

`solve_network` rename was **scoped** to stochastic-only files (`src/stochastic/simulation.py`, its `__init__`, `src/methods/stochastic.py`) because `src/analytic/jackson.py` also has a `solve_network` with the same signature that we intentionally leave under the old name. Scoping avoided collision.

### B9 — `aggregate_network → aggregate_net`, `check_requirements → check_reqs`

7 files: `src/analytic/{metrics,__init__}.py`, `src/methods/{analytic,experiment,stochastic}.py`, `src/view/qn_diagram.py` (overlay refs in plotter docstring), `tests/analytic/test_metrics.py`.

### B10 — `sweep_architecture → sweep_arch`, `_find_max_stable_lambda_factor → _find_max_stable_lam_factor`, networks `_setpoint → read_setpoint`

5 wide-rename files + scoped `_setpoint → read_setpoint` in `src/dimensional/networks.py` and its test. The naive sweep initially corrupted the JSON Variable-dict key string `"_setpoint"` in networks.py:61 and networks.py:363 — caught immediately and reverted (the JSON key is profile schema; only the Python function name changes). The word-boundary regex was safe for most cases but the dict-subscript context `vars_block[_sym]["_setpoint"]` still picked up the match.

### B11 — `ClientConfig / RampConfig / CascadeConfig → ClientCfg / RampCfg / CascadeCfg`

5 files: `src/experiment/client.py`, `src/methods/experiment.py`, `src/scripts/demo_client.py`, `tests/experiment/{test_client,test_launcher}.py`. **Fields `entry_service`, `request_size_bytes`, `request_sizes_by_kind` were intentionally NOT renamed** — they mirror keys in `data/config/method/experiment.json` verbatim, so renaming them would force an in-lockstep JSON-config edit and break every historical run's config-snapshot. Classes-only rename is the minimal-blast option.

### Verification + notebook re-execution

All 338 tests pass after each sub-sweep. Notebook import-cell smoke test passes for 01 / 02 / 03 / 04 / 05; 06-comparison still fails but with a pre-existing `ImportError: _async_run` (the comparison method module is the next milestone, not built yet — unrelated to these renames). Full notebook re-execution queued for 01-05 so the rendered JSON carries the new symbol names in code cells.

### Policy pins adopted during the sweep

- **Wire-schema fields are off-limits to R2 renames** when they appear as JSON config keys or CSV column names persisted in `data/results/`. Only Python identifiers flip.
- **Variable-dict JSON keys** (`_setpoint`, `_mean`, `_data`, `_dims`, ...) are PACS contract and must never be touched by a Python-side sweep, even when a Python function shares the name.
- **Scoped renames** (`solve_network`, `_setpoint`) beat whole-repo sweeps when two modules share a name intentionally; the sweep script targeted specific file lists rather than running a global regex.

### Stage state after this sweep

All 11 B-batches (B1 through B12; no B2 because the initial number skipped) are now closed. `notes/audit.md` B-batch tables above are historical record; the deferred queue is empty. Only outstanding audit gap is `tests/view/test_qn_diagram.py` (the 1300-line matplotlib / networkx module has no mirrored test); flagged at 0.10 close and still flagged now.

## 2026-04-22 follow-up — `plot_dim_topology` follow-up tweaks (user feedback)

Five adjustments to the dimensional-topology plotter based on user review of the baseline render.

**1. Legend formulas.** `DIM_GLOSSARY_DEFAULT` rewritten from the placeholder "Occupancy / Service intensity / Fault exposure / Memory footprint" single-symbol lines to the full closed-form definitions:
- `$\theta = L/K$`: Occupancy (queue fill ratio)
- `$\sigma = W\lambda/L$`: Stall (Little's-law residual; blocking)
- `$\eta = \chi K/(\mu c)$`: Effective-yield (utilisation headroom)
- `$\phi = M_{act}/M_{buf}$`: Memory-usage (buffer fill)

These are the same definitions the notebook's opening markdown cell quotes; the legend and the narrative now agree.

**2. Compact node labels.** Every node now shows only `<key>` + `θ = <value>`. The prior 5-line label (key + all four coefficients) was unreadable at 18x22" figure size; the full breakdown now lives in the per-node table below the graph.

**3. Node colouring switched to $\eta$ with min-max normalisation.** Default `color_by="eta"` (was `"theta"`). Reason: `theta` is bounded to `[0, 1]` but at the uniform-baseline initialisation collapses to a tight 0.00-0.21 band, so the coolwarm colourbar barely exercised its range. `eta` is unbounded (varies 0.20-2.85 on baseline; higher on adapted scenarios) and shows real architectural variation. Normalisation also switched from capped-at-1 (`max(vmax, 1.0)`) to data-driven `(vmin, vmax)` so the hottest node always saturates red and the coolest saturates blue regardless of absolute magnitude. Colourbar label updated to track the selected coefficient symbol.

**4. Architecture-average overlay.** New private helper `_add_dim_network_summary` mirrors the queueing view's `_add_network_summary` but reports `mean(theta) / mean(sigma) / mean(eta) / mean(phi)` across every component, not queueing metrics. Rendered in a lightblue text box at the graph's upper-right corner; overbar notation (`$\bar{\theta}$`, `$\bar{\sigma}$`, …) signals "average over components".

**5. Component column thinned.** Table column widths changed from `[0.22] + [0.14]×4` to `[0.14] + [0.18]×4` — artifact keys are short (`TAS_{1}`, `MAS_{2}`, …) so the Component column no longer needs 22 % of the table width; the coefficient columns benefit from the reclaimed space.

**Verification:** `plot_dim_topology` smoke-ran on baseline (13 components), figure renders correctly for all five changes; `tests/dimensional/` 66 passed; 03-dimensional notebook re-executed end-to-end; `data/img/dimensional/baseline/topology.png` reflects every adjustment.

**Rule-check (R1–R15):** new helper `_add_dim_network_summary` carries a single-line `*()*` lead-in docstring + Args block (R1), uses `_TEXT_BLACK` not `"black"` (matplotlib SVG quirk), wraps Greek + overbar in mathtext `$\mathbf{\overline{...}}$` (R14 British "utilisation" already in place), keyword-only param `corner`. No inline ternaries; explicit `if`/`else` for corner anchoring. `DIM_GLOSSARY_DEFAULT` now carries the full formulas so the legend matches the narrative — no value-laden language to trip R15.

## 2026-04-22 follow-up — `plot_dim_topology` round-2 tweaks

User flagged five more refinements after the first render with the full formulas.

1. **Coefficient columns thinner.** Table `_col_widths` went `[0.14] + [0.18]*4` → `[0.12] + [0.12]*4`. Artifact keys and 4-decimal coefficient values both fit comfortably in 12 % of the table width; the reclaimed margin stops the table from running edge-to-edge.
2. **Network summary line format.** Each line in the `NETWORK` overlay now reads `$\bar{sym}$ (Name): value` (e.g. `$\bar{\theta}$ (Occupancy): 0.0537`) instead of bare `$\bar{sym}$: value`. New `_DIM_COEF_NAMES` map added alongside `_DIM_COEF_SYMS`; reason: at this level of reader context, a bare `\bar{\eta}` is ambiguous, pairing it with the word "Effective-yield" makes the overlay legible without going to the legend.
3. **Legend uses `\frac{}{}`** for every formula (`$\theta = \frac{L}{K}$`, `$\sigma = \frac{W\lambda}{L}$`, `$\eta = \frac{\chi K}{\mu c}$`, `$\phi = \frac{M_{act}}{M_{buf}}$`). Inline slashes made the formulas wide; vertical fractions keep the bounding box half the width and read cleaner against the Greek-letter lead.
4. **"Node Coefficient Table" heading** moved from figure-y `0.27` → `0.24` so it no longer overlaps the legend anchored to the graph axis's lower-right corner. Legend sits in axes coords (0..1 inside the graph axis); figtext sits in figure coords; the `0.24` vs `0.27` is a geometry offset of ~3 % of figure height.
5. **Colouring by $\eta$** — already the default from the previous round (no change needed).

**Verification:** smoke-rendered `data/img/dimensional/baseline/topology.png`; all five adjustments visible in the PNG. `03-dimensional.ipynb` re-executed end-to-end; `data/img/dimensional/{baseline,s1,s2,aggregate}/topology.{png,svg}` regenerated.

## 2026-04-22 follow-up — `plot_dim_topology` round-3 tweaks + `plot_qn_topology` label switch

Three more refinements on `plot_dim_topology` + one change to `plot_qn_topology` based on user review.

1. **$\eta$ formula uses `\cdot`** between multi-symbol numerator / denominator factors: `$\eta = \frac{\chi \cdot K}{\mu \cdot c}$` (was `$\eta = \frac{\chi K}{\mu c}$`). Matplotlib mathtext kerns tightly-stacked Greek + Latin letters, making `\chi K` readable only at large font sizes; explicit `\cdot` forces a visible multiplication glyph.
2. **Scientific notation (`.2e`) everywhere** on the dimensional view: table cells (was `.4f`), NETWORK overlay (was `.4f`), node labels (was `.2f` for theta). Dimensional coefficients vary orders of magnitude across adaptations — mixing fixed-point and decimal-aligned formats hid that variation. `.2e` gives uniform width + 3 sig figs.
3. **Colourbar + normalisation policy pinned**: `color_by="eta"` default; normalisation uses `nds[color_by].min()` / `.max()` (data-driven min-max, no fixed cap at 1). This was already the case from round-2 but user flagged it explicitly; now documented in the memory so future callers don't try to cap at 1.

**`plot_qn_topology` label change (separate but landed in the same turn):**

- Node label switched from `$\rho = 0.38$` to `$L = 3.82$` (avg number in system, absolute units). Colouring still tracks `rho` via `_node_colors` — only the displayed value changed. Reason: L carries units (requests), ρ is unitless and already visible via the colourbar; the second line on the node is more informative with L.
- Regenerated `data/img/analytic/{baseline,s1,s2,aggregate}/topology.{png,svg}` via full `01-analytic.ipynb` re-execution.
- `nd_diffmap` / `nd_heatmap` / `net_bars` / `net_delta` plotters untouched; table under the graph still shows rho in its own column.

**Verification:** four dimensional + four analytic topology PNGs regenerated; the NETWORK box and the table now both carry the same coefficient values in the same `.2e` format; the analytic baseline MAS_{1} node shows `L = 0.21` (requests), `$\rho = 0.383$` still in the colour scale.

## 2026-04-24 follow-up — calibration trio audit (`src/methods/calibration.py` + `src/view/characterization.py` + `src/io/tooling.py` + `00-calibration.ipynb`)

Paired style sweep across the calibration subsystem's three Python modules plus the thin notebook, following the 15-rule checklist. Scope set by user direction; policy pins from the 2026-04-22 B-batch closure are honoured (wire-schema identifiers, JSON config keys, and PACS `_setpoint` keys are off-limits to R2 renames).

### Scope

- `src/methods/calibration.py` (1505 lines)
- `src/view/characterization.py` (429 lines)
- `src/io/tooling.py` (187 lines)
- `00-calibration.ipynb` (19 cells)

### Held-back identifiers (policy pins, not audited renames)

- Config-key mirrors in `data/config/method/calibration.json`: `adaptation`, `rates`, `trials_per_rate`, `min_samples_per_kind`, `max_probe_window_s`, `cascade_mode`, `cascade_threshold`, `cascade_window`, `target_loss_pct`, `entry_service`, `n_con_usr`, `samples_per_level`, `uvicorn_backlog`, `httpx_timeout_s`. Python parameter names mirror these keys verbatim so a JSON edit and the kwarg stay in lockstep; any R2 rename here would force a simultaneous config-schema edit and break historical calibration envelopes already on disk. Same policy as B11 for `entry_service` / `request_size_bytes`.
- Module filename `src/view/characterization.py` is the established import path (CLAUDE.md references it; `src.view` re-exports its three plotters). The file name stays on the US spelling; prose inside the module uses British per R14 (`Visualisation`, `utilisation`, `characterise`).
- JSON envelope keys (`handler_scaling`, `host_profile`, `rate_sweep`, `calibrated_rate`, `mean_loss_pct`, `loopback.median_us`, `jitter.p99_us`, ...) are wire-schema and stay.

### Findings + fixes

**`src/methods/calibration.py`** — four items fixed in place:

1. **R10 em-dash** at module docstring line 6: `characterization method — sibling to` rewritten as `characterisation method; sibling to` (semicolon replaces the em-dash AND flips to British spelling per R14).
2. **R14 British English** at three prose sites: `characterization` → `characterisation` in the module docstring (line 6), the `run_rate_sweep` docstring (line 883, "host-floor AND rate-saturation characterisation"), and the argparse description (line 1341, "Per-host noise-floor characterisation for the "). File path / module filename unchanged.
3. **R10 bare-dash divider** at the inline comment on line 1292 (`context manager on purpose -- the experiment method`) rewritten with a semicolon so the prose stays one sentence. Section banner comment at line 1392 (`# -- rate-sweep flags ... --`) kept as-is; R9 preserves section banners for human auditors even when they use `--`.
4. **R12 import grouping**: `import gc` moved from the `# scientific stack` block to the `# native python modules` block. `gc` is stdlib; the prior grouping was a leftover from when the file only had `numpy` as the non-stdlib import.

No R2 / R3 / R5 / R8 / R11 / R13 / R15 issues found. Spot-checked:
- **R1 single-line bullets / Args**: every Args / Returns / Raises entry in the 30+ public + private functions fits on one line.
- **R3 verb-first**: every public function (`snapshot_host_profile`, `measure_timer`, `measure_jitter`, `measure_loopback`, `measure_handler_scaling`, `run_rate_sweep`, `run`, `main`) and every private helper (`_banner`, `_build_ping_app`, `_run_concurrent_worker`, `_run_probes_in_dedicated_loop`, `_print_phase_marker`, `_parse_n_con_usr`, `_parse_rates`, `_batch_size_for`, `_read_lambda_z_at`, `_run_single_rate_probe`, `_summarise_rate_trial`, `_aggregate_rate_trials`, `_find_highest_sustainable_rate`, `_build_output_path`, `_write_json`, `_print_summary`, `_run_async_probes`, `_build_argparser`) is verb-first; the `_UvicornThread` and nested `_MEMSTAT` classes are legitimate nouns.
- **R4 type hints**: every signature carries parameter + return hints; `Optional[Any]` is used for callable slots (`on_level_start` / `on_level_done` / `on_phase_start`) rather than a tighter `Callable[..., None]` but the hint is present (R4 says hints, not precision).
- **R5 `_` prefix**: all locals prefix-underscored; module-level constants (`_DEFAULT_*`, `_CALIB_CFG`, `_CALIB_DIR`, `_TARGET_TICK_S`, `_JITTER_TARGET_NS`) keep the underscore because they are private to the module. Lowercase imported names (`asyncio`, `numpy as np`) deliberately NOT renamed (R5 exempts imported names).
- **R8 inline ternaries**: `rg " if .+ else "` returns nothing on the file; every conditional is an explicit `if`/`else` block or early-return (e.g. `_batch_size_for`, `_summarise_rate_trial`, `_aggregate_rate_trials`, `_build_output_path`).
- **R12 lazy imports**: `from src.io.config import load_method_cfg` inside `_load_cfg`, `from src.io import load_profile` inside `_read_lambda_z_at`, and `from src.io import load_method_cfg` + `from src.methods.experiment import run as _experiment_run` inside `_run_single_rate_probe` all justify the exception: `_load_cfg` breaks a potential circular import chain (the io module reads calibration config), and the experiment-run import is a heavy optional dep that is only paid when the rate sweep is opted into. `ctypes` is imported under `sys.platform == "win32"` guards in `snapshot_host_profile` and `_windows_timer_resolution` — OS-conditional guards are not in scope for R12.

**`src/view/characterization.py`** — one item fixed in place:

1. **R4 return-type annotation** on `_sort_n_con_usr_items`: was `def _sort_n_con_usr_items(handler: Dict[str, Dict[str, float]]):` (no return hint); rewritten as `-> List[tuple]`. Docstring already documented the shape as `list[tuple[int, dict]]`; signature now carries the hint. Kept the base `tuple` rather than `Tuple[int, Dict[str, float]]` because the inner shape varies depending on which stats the envelope recorded; the docstring is authoritative for the nested shape.

No other issues found:
- **R10 em-dashes / arrows**: `rg "—|→|←"` returns nothing. The module-level docstring uses colons and parentheses for list separation, no unicode dividers.
- **R14 British English**: module docstring says "Visualisation" (British). Prose throughout reads British ("annotated", "neutral", "legible"). The word "characterization" appears only in the `Module view/characterization.py` self-reference, which is the filesystem path.
- **R15 neutral terminology**: docstrings speak of `saturation`, `bar chart`, `gradient`, `percentile rank`; no `improvement` / `degradation` framing. The rate-sweep docstring's "highest passing rate" and "the bar" are neutral performance-gate language.
- **R12 imports**: three grouped blocks (`# native python modules`, `# scientific stack`, `# shared view helpers`), ordered per convention; no lazy imports.
- **R13 trivial getters**: module has no classes, so N/A.

**`src/io/tooling.py`** — no fixes needed. Full pass:

- **R1 single-line**: every Args / Returns entry on one line; no forced wrapping.
- **R3 verb-first**: `find_latest_calibration`, `load_latest_calibration`, `calibration_floor_us`, `calibration_band_us`, `rate_sweep_calibrated_rate`, `rate_sweep_loss_at`, `calibration_age_hours`. The last three are domain accessors rather than imperative verbs but fit CLAUDE.md's "read/derive" accessor pattern (they extract numeric fields the reporting path needs); the `*_us` / `*_hours` suffix makes them unambiguous as getters of a specific unit, which is the canonical project pattern for `load_*` + `*_us` numeric accessors. Not a rule violation.
- **R4 type hints**: every signature fully hinted (`Optional[Path]`, `Optional[Dict[str, Any]]`, `float`, `Optional[float]`).
- **R5 `_` prefix**: all locals prefix-underscored.
- **R8 inline ternaries**: none found.
- **R10 em-dashes / arrows**: none.
- **R12 imports**: one top-level block, stdlib only.
- **R14 British English**: "normalised", "symmetric", "unparseable" — all British spellings already.
- **R15**: no loaded language.

**`00-calibration.ipynb`** — three markdown cells rewritten:

1. **Cell `nb-calib-intro`** — bare-dash dividers (` -- `) replaced:
   - Title `# Calibration (host noise-floor) -- CS-01 TAS` → colon-separated `: CS-01 TAS`.
   - `Four probes -- timer resolution, ... -- produce` → `Four probes (timer resolution, ...) produce`.
   - Three output bullets `<path> -- description` → `<path>: description`.
2. **Cell `nb-calib-sec-summary`** — every bullet `**key** -- description` → `**key**: description` (seven bullets).
3. **Cell `nb-calib-sec-scaling-table`** — `stack up -- often the real cause of prototype degradation at high rates.` → `stack up; often the real driver of prototype latency rise at high rates.`. R15 swap (`degradation` → `latency rise`, neutral) and R10 bare-dash → semicolon in the same edit.

Code cells left untouched on purpose:
- The `print("rate_sweep block absent -- set _RUN_RATE_SWEEP ...")` string in cell `c7e35b6c` uses `--` inside a user-facing print, which is allowed (R10 targets U+2014 em-dash, not ASCII double-hyphen). The Notebook Style Pass rule governs MARKDOWN cells; plain source strings stay.
- Other code cells (`nb-calib-setup`, `nb-calib-run`, `nb-calib-host`, `nb-calib-summary`, `nb-calib-scaling-table`, `nb-calib-dashboard`, `nb-calib-scaling`, `nb-calib-apply`) import the three public plotters + `run`, do no logic on their own, and compose tight pandas display frames. No style issues.

### Verification

- `rg "—|→|←" src/methods/calibration.py src/view/characterization.py src/io/tooling.py` returns nothing after the fixes.
- `rg " -- "` on the notebook markdown cells (Python-scripted check) returns zero hits.
- `rg "characterization" src/` leaves only the filesystem path `src/view/characterization.py` and its in-file self-reference (the `Module view/characterization.py` header line), which are intentional.
- `rg "improve|improvement|degradation"` on the four audited artifacts returns nothing after the notebook fix.
- Audit-surface line counts unchanged within ±4 lines per file (pure prose + import regrouping, no structural edits).

### State after this sweep

Calibration trio + thin notebook are clean against the 15-rule checklist. Next audit surface: `05-experimental.ipynb` + `06-yoly-experimental.ipynb` markdown cells (notebook-style pass not yet applied there) and the `tests/methods/test_calibration.py` mirror whenever it lands.

## 2026-04-24 follow-up — calibration Route B coefficient block audit (`src/methods/calibration.py`)

`src/methods/calibration.py` grew by ~170 lines after the first-pass audit: new `_CALIB_DIM_TAG` constant at line 1454, new `_derive_calib_coefs_arrays` private helper (lines 1457-1548) that walks the `handler_scaling` + `loopback` blocks and produces Route-B dimensionless coefficient arrays, and a `derive_calib_coefs` public entry (lines 1551-1605) that wraps the helper into a JSON-ready card the `src.view.dc_charts.plot_yoly_chart` plotter consumes. Re-running the 15-rule checklist over the new block.

**Fixes applied:**

1. **R8 inline ternary** at line 1594: `_mu_val = float(_arrays[f"\\mu_{{{tag}}}"][0]) if len(_levels) > 0 else 0.0` → explicit `if len(_levels) > 0: / else:` block. Only inline-ternary hit across the whole file (`rg " if .+ else "` confirms).

**No other issues found:**

- **R1 single-line Args/Returns**: every field description on one line; the long `Returns` line in `_derive_calib_coefs_arrays` is deliberately unwrapped (linter owns wrapping per `feedback_docstring_wrapping`).
- **R2 acronyms**: `coefs`, `c_srv`, `_mu`, `_lam`, `_cfg`, `_r_arr`, `_n_arr`, `_k_capacity`, `_r_safe` all in canonical short form. `payload_size_bytes` kept (wire-schema config-key mirror in `data/config/method/experiment.json`).
- **R3 verb-first**: `_derive_calib_coefs_arrays` + `derive_calib_coefs` are verb-first ("derive"); the helper's 5-acronym budget is `calib / coefs / arrays` which fits the cap.
- **R4 type hints**: both signatures fully hinted including return (`Dict[str, np.ndarray]` and `Dict[str, Any]`); kwargs-only defaults declared after `*,` as the view plotters do.
- **R5 `_` prefix**: every local prefix-underscored; module-level `_CALIB_DIM_TAG` also prefix-underscored because it is private to the module even though the value flows out via `derive_calib_coefs`.
- **R8 inline ternaries (rest of block)**: after the single fix above, `_theta` / `_sigma` / `_eta` / `_phi` derivations all use explicit `if _l_load.size > 0 and _l_load.max() > 0:` / `if _mu > 0 and c_srv > 0:` / `if _bytes > 0:` blocks.
- **R10 em-dashes**: `rg "—|→|←"` on the whole file returns zero.
- **R12 imports**: no new imports (`numpy as np` + stdlib already at module top).
- **R14 British English**: docstring uses "serialisable" (British).
- **R15 neutral terminology**: coefficient names and their wording ("in-flight", "queueing", "system-capacity") are neutral; no `improvement` / `degradation` framing.

**Preserved section banners (R9):** the `# -- rate-sweep flags ... --` marker at line 1402 kept as-is; section banners for human auditors are exempt from R10 per the audit-rules table.

**Verification:** `rg "—|→|←"`, `rg "characterization|visualization|behavior|utilization|colour"`, and `rg " if .+ else "` all return zero on the file after the fix. Audit pass closed for the expanded calibration module.

## 2026-04-24 follow-up — R16 comment-density policy + multi-module sweep

**New rule R16** added to the audit table above: a single `#` comment gets at most one line; stacked `# ...` runs (two or more consecutive comment lines) are forbidden; collapse to a one-line why-comment above the code, or drop the comment if the why is obvious from names. Exceptions are R9 section banners and import-group headers (`# native python modules`, `# scientific stack`, `# web stack`, `# shared view helpers`, `# local modules`, `# test stack`, `# modules under test`, `# target under test`, `# data types`). Dataclass field comments continue to sit on their own line above each field (R6) with pedagogy preserved (R7), but never multi-line. Rationale from user feedback: adjacent `#` blocks break visual flow and duplicate what a tight `*()*` docstring lead-in already conveys.

**Documented in:**
- [CLAUDE.md](../CLAUDE.md) "Coding Conventions" section (bullet under "Don't manually wrap docstring").
- [.claude/skills/develop/coding-conventions.md](../.claude/skills/develop/coding-conventions.md) Style Rules block (two bullets; the second covers the dataclass-field case explicitly).
- [notes/audit.md](audit.md) rule table, R16 row.

**R16 sweep applied in this session (modules touched, comment runs collapsed):**

| Module | Multi-line `#` runs collapsed | Other fixes in same pass |
|---|---|---|
| `src/methods/calibration.py` | 16 | em-dash → semicolon, `characterization` → `characterisation` (×3 prose), `import gc` regrouped, R8 ternary on `_mu_val` |
| `src/view/characterization.py` | 8 | R4 return-type annotation on `_sort_n_con_usr_items` |
| `src/io/tooling.py` | 1 | — |
| `src/experiment/services/base.py` | 9 | — |
| `src/view/dc_charts.py` | 24 | 18 R8 ternaries rewritten, two ` -- ` bare-dash dividers → semicolon |
| `tests/methods/test_experiment.py` | 1 | R8 ternary on `_result` fixture |
| `tests/methods/test_calibration.py` | 4 | `import math` + `import pandas as pd` lifted to module top, two nested-literal returns broken into sequential intermediates |
| `00-calibration.ipynb` | — | 3 markdown cells rewritten to drop bare-dash dividers, R15 `degradation` → `latency rise` |

Held-back identifiers across the sweep (policy pins, not renamed): JSON-config-mirrored Python params (`adaptation`, `entry_service`, `cascade_mode/threshold/window`, `n_con_usr`, `samples_per_level`, `uvicorn_backlog`, `httpx_timeout_s`, `rho_grid`, `min_samples_per_kind`, ...), wire-schema CSV / envelope keys (`handler_scaling`, `loopback`, `rate_sweep`, `host_profile`, `calibrated_rate`, `mean_loss_pct`, `service_name`, `message`, `request_id`, `kind`, `size_bytes`, `c`, `K`), and the `src/view/characterization.py` filename (established import path; prose inside the file uses British `characterisation` / `utilisation`).

**State after this sweep:** R16 policy captured durably in CLAUDE.md + skill + audit table; every calibration-subsystem module (`src.methods.calibration`, `src.view.characterization`, `src.io.tooling`, `src.experiment.services.base`, `src.view.dc_charts`) plus the two paired test modules and the thin notebook are clean against the R1-R16 set. Next audit surface: the remaining `src/experiment/**` modules (`launcher.py`, `client.py`, `payload.py`, `registry.py`, `instances/*.py`, `services/{atomic,composite,instruments}.py`) + their test mirrors, then the `05-experimental.ipynb` / `06-yoly-experimental.ipynb` / `07-comparison.ipynb` notebook-style passes.

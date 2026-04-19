# Quickstart — TAS

Get the pipeline running locally. See `notes/workflow.md` for the method-by-method contract and the naming convention.

## 1. Prerequisites

- Python 3.12+
- Sibling checkout of [`PyDASA`](../../PyDASA) — this project consumes its built wheel
- Git Bash / PowerShell on Windows, or any POSIX shell

## 2. Build the PyDASA wheel (once, or after PyDASA changes)

From `../PyDASA`:

```bash
python -m build
```

Wheel lands in `../PyDASA/dist/pydasa-<version>-py3-none-any.whl`. `requirements.txt` pins a specific wheel path — update it if the version changes.

## 3. Create the virtual environment

```bash
python -m venv venv
source venv/Scripts/activate     # Git Bash on Windows
# or: .\venv\Scripts\activate    # PowerShell
pip install -r requirements.txt
```

## 4. Run the pipeline

Each method has a CLI **and** a notebook. Both call the same `run()` and produce byte-identical artifacts.

### One CLI shape, every method

```bash
python -m src.methods.<method> --adaptation <baseline|s1|s2|aggregate> [--profile dflt]
```

### Adaptation axis

| Value | Meaning | Loads |
|---|---|---|
| `baseline` | Before adaptation (MAPE-K inert) | `profile/dflt.json`, scenario `baseline` |
| `s1` | S1 adaptation (service-failure handling) | `profile/opti.json`, scenario `s1` (opti routing + dflt services) |
| `s2` | S2 adaptation (response-time handling) | `profile/opti.json`, scenario `s2` (dflt routing + opti services) |
| `aggregate` | Both S1 and S2 applied together | `profile/opti.json`, scenario `aggregate` (opti routing + opti services) |

### Full matrix (CLI path — 20 runs total)

```bash
for method in analytic stochastic dimensional experiment; do
  for adaptation in baseline s1 s2 aggregate; do
    python -m src.methods.$method --adaptation $adaptation
  done
done

for adaptation in baseline s1 s2 aggregate; do
  python -m src.methods.comparison --adaptation $adaptation
done
```

### Notebook path (5 notebooks)

```bash
jupyter lab
```

`Run All` each in order: `analytic.ipynb` → `stochastic.ipynb` → `dimensional.ipynb` → `experiment.ipynb` → `comparison.ipynb`. Each notebook loops over the adaptation axis for its method.

## 5. Output map

Everything lands under `data/results/<method>/<adaptation>/` and `assets/img/<method>/<adaptation>/`:

- `<profile>.json` — one JSON per run, PACS-style. Always contains `variables` (PyDASA dict with `_data` populated); dimensional runs add `coefficients` and `pi_groups`; comparison runs add `deltas`.
- `requirements.json` — R1/R2/R3 pass/fail for this run, profile-agnostic.
- `*.png`, `*.svg` — figures under the mirrored `assets/img/` tree.

Example: `data/results/dimensional/s1/dflt.json` carries variables + coefficients + π-groups for the S1 adaptation under the `dflt` profile.

## 6. Validation criteria (R1 / R2 / R3)

Every run also writes a profile-agnostic `requirements.json` reporting pass/fail against Cámara 2023 targets:

| Requirement | Metric | Threshold | Lens |
|---|---|---|---|
| R1 | average failure rate | ≤ 0.03 % | Availability |
| R2 | average response time | ≤ 26 ms | Performance |
| R3 | average cost | minimise subject to R1 ∧ R2 | Cost |

The comparison method rolls these up across all four evaluation methods.

## 7. Run tests

```bash
pytest -q
pytest tests/analytic -v          # just analytic's unit tests
pytest tests/methods -v           # method integration tests
```

## 8. Reference

- Prior version (frozen, read-only): `__OLD__/`
- Method contracts (audit surface): `notes/workflow.md`
- Case context (full record): `notes/cs_context.md`
- Case objective (narrative): `notes/cs_objective.md`
- Command cheatsheet: `notes/commands.md`
- Decision log: `notes/devlog.md`

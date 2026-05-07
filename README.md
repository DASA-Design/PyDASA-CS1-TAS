# PyDASA-CS1-TAS

DASA (Dimensional Analysis for Software Architecture) evaluation of the **Tele Assistance System** self-adaptive exemplar (Weyns & Calinescu, SEAMS 2015). Consumes the sibling [`PyDASA`](../PyDASA) library as a pinned wheel; produces the metric JSONs and figures that ground the DASA evaluation.

## Status

- **Implemented**: analytic (closed-form QN), stochastic (SimPy DES), dimensional (PyDASA π-groups + coefficients).
- **Archived**: the previous experiment / calibration build is frozen under [`__OLD__/`](__OLD__/) as a read-only reference oracle. The new experiment is being rebuilt under [`src/experimental/`](src/experimental/).
- **Pending**: comparison method (cross-method R1/R2/R3 verdicts).

## Validation criteria (Cámara 2023)

| Requirement | Metric | Threshold | Lens |
|---|---|---|---|
| R1 | average failure rate | ≤ 0.03 % | Availability |
| R2 | average response time | ≤ 26 ms | Performance |
| R3 | average cost | minimise subject to R1 ∧ R2 | Cost |

## Setup

```bash
python -m venv venv && source venv/Scripts/activate   # Git Bash on Windows
pip install -r requirements.txt
```

`requirements.txt` pins a specific PyDASA wheel from the sibling checkout. After bumping PyDASA, rebuild + reinstall:

```bash
cd ../PyDASA && python -m build
pip install --force-reinstall ../PyDASA/dist/pydasa-<ver>-py3-none-any.whl
```

## Run

```bash
python -m src.methods.<method> --adaptation <baseline|s1|s2|aggregate>
jupyter lab          # for the notebooks
```

Surviving methods: `analytic`, `stochastic`, `dimensional`. Surviving notebooks: `01-analytic.ipynb`, `02-stochastic.ipynb`, `03-dimensional.ipynb`, `04-yoly.ipynb`. Results land at `data/results/<method>/<adaptation>/<profile>.json` plus `requirements.json`; figures at `data/img/<method>/<adaptation>/`.

## Tests

```bash
pytest tests/
```

180 tests on the surviving subset.

## Pointers

- [`notes/case-study.md`](notes/case-study.md) — case-study record (architecture, scenarios, ADRs, references)
- [`notes/procedure.md`](notes/procedure.md) — methodology + hypothesis structure
- [`notes/prototype.md`](notes/prototype.md) — apparatus design for the new experiment
- [`__OLD__/`](__OLD__/) — frozen prior implementation (filesystem-only, gitignored)
- [`assets/docs/`](assets/docs/) — case-study writeups + reference papers
- [`log/devlog.md`](log/devlog.md) — decision log
- [`CLAUDE.md`](CLAUDE.md) — coding + notebook conventions

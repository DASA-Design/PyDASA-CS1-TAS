# PyDASA-CS1-TAS — Tele Assistance System Case Study

Reproducible DASA (Dimensional Analysis for Software Architecture) evaluation of the **Tele Assistance System** self-adaptive exemplar (Weyns & Calinescu, 2015). Consumes the sibling [`PyDASA`](../PyDASA) library as a pinned wheel; produces the data and figures that ground the DASA evaluation of TAS.

## What this repo is

- **A reproducible pipeline**, not a library. The output is a matrix of metric JSONs and figures that demonstrate DASA on a published self-adaptive system.
- **One case study** — *CS-01 TAS*. The sibling IoT-SDP case study lives in its own repo.
- **Five evaluation methods** run over **four adaptation states**. 5 × 4 = **20 runs**.

## Evaluation methods

| Method | Module | Notebook | Produces |
|---|---|---|---|
| **analytic** | `src/methods/analytic.py` | `analytic.ipynb` | Closed-form QN metrics (M/M/c/K + Jackson) |
| **stochastic** | `src/methods/stochastic.py` | `stochastic.ipynb` | SimPy DES ground truth with 95 % CIs |
| **dimensional** | `src/methods/dimensional.py` | `dimensional.ipynb` | PyDASA π-groups, coefficients, Monte Carlo |
| **experiment** | `src/methods/experiment.py` | `experiment.ipynb` | Mock ReSeP + ActivFORMS-lite reference run |
| **comparison** | `src/methods/comparison.py` | `comparison.ipynb` | Cross-method deltas + R1/R2/R3 verdicts |

## Adaptation axis

| Value | Meaning | Loads |
|---|---|---|
| `baseline` | Before adaptation (MAPE-K inert) | `profile/dflt.json` only |
| `s1` | S1 service-failure adaptation (Retry-style) | profile + `adaptation/s1.json` |
| `s2` | S2 response-time adaptation (Select-Reliable-style) | profile + `adaptation/s2.json` |
| `aggregate` | Both S1 and S2 applied together (realistic deployment) | profile + both overrides |

## Validation criteria (Cámara et al., 2023)

| Requirement | Metric | Threshold | Lens |
|---|---|---|---|
| R1 | average failure rate | ≤ 0.03 % | Availability |
| R2 | average response time | ≤ 26 ms | Performance |
| R3 | average cost | minimise subject to R1 ∧ R2 | Cost |

Every run writes a `requirements.json` with pass/fail per requirement. The `comparison` method aggregates across methods.

## Quick start

```bash
python -m venv venv && source venv/Scripts/activate
pip install -r requirements.txt

# run one cell of the matrix
python -m src.methods.analytic --adaptation baseline

# or run the notebooks
jupyter lab
```

Full setup and the 20-run matrix in [notes/quickstart.md](notes/quickstart.md).

## Repository layout

```
├── analytic.ipynb · stochastic.ipynb · dimensional.ipynb · experiment.ipynb · comparison.ipynb
├── src/
│   ├── methods/              # orchestrators (one per method)
│   ├── analytic/  stochastic/  dimensional/  experiment/
│   └── view/  io/  utils/
├── data/
│   ├── config/{profile,adaptation,method}/
│   └── results/<method>/<adaptation>/<profile>.json + requirements.json
├── assets/
│   └── img/<method>/<adaptation>/
├── tests/
├── notes/                    # context, objective, workflow, quickstart, commands, devlog
├── __OLD__/                  # frozen prior implementation (reference until superseded)
├── CLAUDE.md                 # Claude Code project guide
├── SUMMARY.md
└── requirements.txt
```

## Documentation map

- **[notes/quickstart.md](notes/quickstart.md)** — setup and how to run the pipeline
- **[notes/workflow.md](notes/workflow.md)** — full method contracts (audit surface)
- **[notes/cs_context.md](notes/cs_context.md)** — the case study's full record (architecture, scenarios, ADRs)
- **[notes/cs_objective.md](notes/cs_objective.md)** — case-study narrative
- **[notes/commands.md](notes/commands.md)** — command cheatsheet
- **[notes/devlog.md](notes/devlog.md)** — dated design decisions
- **[CLAUDE.md](CLAUDE.md)** — coding and notebook conventions

## PyDASA dependency

`requirements.txt` pins a specific PyDASA wheel path. After bumping PyDASA:

```bash
cd ../PyDASA && python -m build
pip install --force-reinstall ../PyDASA/dist/pydasa-<ver>-py3-none-any.whl
```

## License

See [LICENSE](LICENSE).

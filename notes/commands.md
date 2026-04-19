# Commands cheatsheet — CS-01 TAS

## Virtual environment

```bash
python -m venv venv
source venv/Scripts/activate     # Git Bash
.\venv\Scripts\activate          # PowerShell
deactivate
```

## Dependencies

```bash
pip install -r requirements.txt
pip freeze > requirements.txt          # re-pin after changes
pip install --force-reinstall ../PyDASA/dist/pydasa-0.3.2-py3-none-any.whl
```

## PyDASA wheel rebuild (from ../PyDASA)

```bash
python -m build                        # preferred
python setup.py bdist_wheel            # legacy
pip install .                          # editable-ish install from source
```

## Pipeline (CLI)

Shape: `python -m src.methods.<method> --adaptation <baseline|s1|s2|aggregate> [--profile dflt]`.

```bash
# single runs
python -m src.methods.analytic    --adaptation baseline
python -m src.methods.stochastic  --adaptation s1
python -m src.methods.dimensional --adaptation s2
python -m src.methods.experiment  --adaptation aggregate
python -m src.methods.comparison  --adaptation aggregate          # no --profile

# full matrix (20 runs)
for method in analytic stochastic dimensional experiment; do
  for adaptation in baseline s1 s2 aggregate; do
    python -m src.methods.$method --adaptation $adaptation
  done
done
for adaptation in baseline s1 s2 aggregate; do
  python -m src.methods.comparison --adaptation $adaptation
done
```

## Jupyter

```bash
jupyter lab                                       # launch
jupyter nbconvert --to html analytic.ipynb        # export rendered notebook
jupyter nbconvert --to script analytic.ipynb      # dump code-only .py
jupyter nbconvert --clear-output --inplace *.ipynb
```

## Tests

```bash
pytest tests/ -v
pytest tests/test_<module>.py::test_<name>
pytest --cov=src tests/
```

## Git

```bash
git status
git add <files> && git commit -m "<msg>"
git log --oneline -20
git diff __OLD__/                      # review what was archived
```

## Case-study data locations

| Kind | Path |
|---|---|
| Input config | `data/config/` |
| Stage results | `data/results/` |
| Figures for notebooks/reports | `assets/img/` |

## Sphinx docs (if re-enabled later)

```bash
sphinx-quickstart
make html
make gettext
sphinx-build -b gettext . _build/gettext
sphinx-intl update -p _build/gettext -l es
sphinx-build -b html -D language=es . _build/html/es
```

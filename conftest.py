# -*- coding: utf-8 -*-
"""Pytest configuration; makes `src.*` imports work from any test path.

# TODO: replace with a pyproject.toml once one is added for build/lint
#       config — move the pythonpath setup into `[tool.pytest.ini_options]`
#       and delete this file.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def pytest_configure(config) -> None:
    """*pytest_configure()* register custom pytest markers so the runner does NOT warn about unknown markers.

    Currently registers:
        - `live_mesh`: tests that spin up a real FastAPI mesh in-process (UvicornThread) or out-of-process (UvicornProcess); skipped from the default suite via `-m "not live_mesh"`. Names the failure-mode axis (mesh-spin-up cost) rather than a coarse speed bucket — see `feedback_dpl_naming_monotone_axis.md` in memory.
    """
    config.addinivalue_line(
        "markers",
        "live_mesh: tests that spin up a real FastAPI mesh; opt-in via "
        "`pytest -m live_mesh` (default suite skips them)")

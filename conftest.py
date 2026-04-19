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

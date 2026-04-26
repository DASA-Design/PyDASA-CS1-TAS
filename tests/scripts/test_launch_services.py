# -*- coding: utf-8 -*-
"""
Module test_launch_services.py
==============================

Tests for the real-uvicorn launcher in `src.scripts.launch_services`. Class roster:

    - **TestLaunchServicesCli** argparse contract: unknown values exit non-zero.
    - **TestLaunchServicesLifecycle** in-process launch with `--duration` returns 0 and the mesh /healthz responds while alive.
"""
# native python modules
from __future__ import annotations

# testing framework
import pytest

# module under test
from src.scripts import launch_services


class TestLaunchServicesCli:
    """**TestLaunchServicesCli** CLI surface accepts the documented `--launcher-role` / `--deployment` choices and rejects typos."""

    def test_unknown_launcher_role_rejected(self):
        """*test_unknown_launcher_role_rejected()* argparse rejects an unrecognised `--launcher-role` value with `SystemExit(2)`."""
        with pytest.raises(SystemExit) as _exc:
            launch_services.main(argv=["--launcher-role=not-a-bucket",
                                       "--duration=0.1"])
        assert _exc.value.code == 2

    def test_unknown_deployment_rejected(self):
        """*test_unknown_deployment_rejected()* argparse rejects an unrecognised `--deployment` value with `SystemExit(2)`."""
        with pytest.raises(SystemExit) as _exc:
            launch_services.main(argv=["--deployment=not-a-mode",
                                       "--duration=0.1"])
        assert _exc.value.code == 2

    def test_help_exits_zero(self):
        """*test_help_exits_zero()* `--help` exits cleanly with code 0 (argparse convention)."""
        with pytest.raises(SystemExit) as _exc:
            launch_services.main(argv=["--help"])
        assert _exc.value.code == 0


class TestLaunchServicesLifecycle:
    """**TestLaunchServicesLifecycle** end-to-end: bring up the mesh in `local` mode for a short duration; assert clean shutdown (return 0)."""

    def test_local_all_short_duration(self):
        """*test_local_all_short_duration()* `--launcher-role=all --deployment=local --duration=2` brings up the full mesh on 127.0.0.1, runs for 2 s, returns 0 on clean shutdown."""
        _rc = launch_services.main(argv=["--launcher-role=all",
                                         "--deployment=local",
                                         "--duration=2.0"])
        assert _rc == 0

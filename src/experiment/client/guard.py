# -*- coding: utf-8 -*-
"""
Module client/guard.py
======================

Detector that watches inbound `RequestRecord`s and decides when the ramp must halt.
"""
# native python modules
from __future__ import annotations

from collections import deque
from typing import Deque, Optional

# local modules
from src.experiment.client.config import CascadeCfg
from src.experiment.client.records import RequestRecord


class StopGuard:
    """*StopGuard* tracks infra-failure history and signals the rate driver to halt the ramp.

    Two halt rules are supported via `cfg.mode`: `"fail_fast"` halts on the first infra failure; `"rolling"` halts when the trailing-window infra-fail share exceeds `cfg.threshold` after the window fills. Once halted, further records are ignored.
    """

    def __init__(self, cfg: CascadeCfg) -> None:
        """*__init__()* hold the spec; allocate the trailing window.

        Args:
            cfg (CascadeCfg): mode + threshold + window spec for the halt rule.
        """
        self.cfg = cfg
        self._window: Deque[bool] = deque(maxlen=cfg.window)
        self._tripped: bool = False
        self._reason: Optional[str] = None

    @property
    def tripped(self) -> bool:
        """*tripped* halt-signal flag.

        Returns:
            bool: True after the first invocation that satisfies the configured halt rule, False until then and after `reset()`.
        """
        return self._tripped

    @property
    def reason(self) -> Optional[str]:
        """*reason* short tag explaining the halt.

        Returns:
            Optional[str]: e.g. `"fail_fast: status=503"` or `"rolling: 0.20 > 0.10 over last 50"`; `None` until the first halt fires.
        """
        return self._reason

    def reset(self) -> None:
        """*reset()* discard accumulated history and re-arm the detector for a fresh ramp."""
        self._window = deque(maxlen=self.cfg.window)
        self._tripped = False
        self._reason = None

    def observe(self, rec: RequestRecord) -> None:
        """*observe()* feed one record into the detector; no-op once halted.

        In `fail_fast` mode any infra failure halts immediately. In `rolling` mode the failure flag is appended to the trailing window; once the window is full, halt fires whenever the share strictly exceeds `cfg.threshold`.

        Args:
            rec (RequestRecord): the completed invocation.
        """
        if not self._tripped:
            _infra = rec.infra_failure
            _is_fail_fast = self.cfg.mode == "fail_fast"
            if _is_fail_fast and _infra:
                self._tripped = True
                self._reason = f"fail_fast: status={rec.status_code}"
            elif not _is_fail_fast:
                self._window.append(_infra)
                _full = len(self._window) >= self.cfg.window
                if _full:
                    _rate = sum(self._window) / len(self._window)
                    _exceeds = _rate > self.cfg.threshold
                    if _exceeds:
                        self._tripped = True
                        _msg = f"rolling: {_rate:.3f} > "
                        _msg += f"{self.cfg.threshold:.3f} "
                        _msg += f"over last {self.cfg.window}"
                        self._reason = _msg

"""Resolve the `slo` executable path for OS schedulers."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

__all__ = ["ScheduleExecutableLocator"]


class ScheduleExecutableLocator:
    """Locate the `slo` executable embedded into launchd/cron entries."""

    @classmethod
    def locate(cls) -> Path:
        """Resolve the `slo` executable path.

        Returns:
            Path: Absolute executable path.

        Raises:
            FileNotFoundError: When `slo` cannot be resolved.
        """
        venv_candidate: Path = Path(sys.executable).resolve().parent / "slo"
        if venv_candidate.exists():
            return venv_candidate
        which_result: str | None = shutil.which("slo")
        if which_result is not None:
            return Path(which_result).resolve()
        raise FileNotFoundError("Could not resolve the slo executable.")

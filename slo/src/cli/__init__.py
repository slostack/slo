"""Console-script entry point for the ``slo`` command (sub-spec 02.a.4)."""

from __future__ import annotations

from src.cli.warnings import suppress_known_dependency_warnings

suppress_known_dependency_warnings()

from src.cli.app import main

__all__ = ["main"]

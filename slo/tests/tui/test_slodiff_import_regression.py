"""Startup regression tests for the slodiff bootstrap containment boundary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class TestSloDiffImportContainment:
    """Prove model and tool startup paths do not eagerly load the Textual view."""

    def test_import_when_core_and_extended_bundle_loads_does_not_eagerly_import_view(self) -> None:
        """Run the real import sequence in a fresh Python process.

        WHAT: Imports the slodiff package and extended tool bundle, constructs the
        real bundle, and verifies the optional Textual view stays unloaded.
        WHO: Guards harness startup against an unavailable view-only dependency.
        WHEN: Runs whenever the Feature 68 startup regression test module executes.
        """
        repository_root: Path = Path(__file__).resolve().parents[2]
        script = """
import sys
import src.tui.slodiff
assert 'src.tui.slodiff.view' not in sys.modules
import src.agents.tools.bundles as bundles
assert 'src.tui.slodiff.view' not in sys.modules
tools = bundles.create_extended_tools()
assert any(tool.name == 'show_git_diff' for tool in tools)
assert 'src.tui.slodiff.view' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

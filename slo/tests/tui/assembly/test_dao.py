"""Focused contract tests for the public Slo TUI assembly configuration."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.tui.assembly.dao import SloTuiAssemblyConfigDAO


class TestSloTuiAssemblyConfigDAO:
    """Validate the immutable closed-scenario assembly input."""

    def test_accepts_only_the_closed_textual_current_scenario(self, tmp_path: Path) -> None:
        """Only the production textual scenario validates and the model is frozen."""
        config: SloTuiAssemblyConfigDAO = SloTuiAssemblyConfigDAO(
            environment_scenario="textual_current",
            workdir=tmp_path,
            workspace_file=tmp_path / "workspace.code-workspace",
            plugin_paths=(tmp_path / "plugin.py",),
        )

        assert config.environment_scenario == "textual_current"
        assert config.plugin_paths == (tmp_path / "plugin.py",)
        with pytest.raises(ValidationError):
            SloTuiAssemblyConfigDAO.model_validate({"environment_scenario": "slotui", "workdir": tmp_path})
        with pytest.raises(ValidationError):
            SloTuiAssemblyConfigDAO.model_validate(
                {
                    "environment_scenario": "textual_current",
                    "workdir": tmp_path,
                    "unexpected": "forbidden",
                }
            )
        with pytest.raises(ValidationError):
            config.workdir = Path("other")

    @pytest.mark.parametrize("field_name", ["workdir", "workspace_file"])
    def test_rejects_non_absolute_paths_before_factory_construction(
        self,
        field_name: str,
        tmp_path: Path,
    ) -> None:
        """Relative interactive paths fail at immutable-config validation time."""
        values: dict[str, object] = {
            "environment_scenario": "textual_current",
            "workdir": tmp_path,
            "workspace_file": tmp_path / "workspace.code-workspace",
        }
        values[field_name] = Path("relative")

        with pytest.raises(ValidationError, match="resolved and absolute"):
            SloTuiAssemblyConfigDAO.model_validate(values)

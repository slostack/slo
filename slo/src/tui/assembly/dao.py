"""Immutable input types for Slo's current interactive TUI assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

__all__ = ["SloTuiAssemblyConfigDAO", "SloTuiEnvironmentScenario"]

SloTuiEnvironmentScenario = Literal["textual_current"]
"""The only interactive presentation scenario permitted by this boundary."""


class SloTuiAssemblyConfigDAO(BaseModel):
    """Carry resolved, immutable facts for one current interactive Slo TUI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    environment_scenario: SloTuiEnvironmentScenario
    workdir: Path
    workspace_file: Path | None = None
    resume_session_id: str | None = None
    plugin_paths: tuple[Path, ...] = ()

    @model_validator(mode="after")
    def _require_resolved_paths(self) -> SloTuiAssemblyConfigDAO:
        """Reject relative interactive paths before assembly can construct collaborators.

        WHAT: Enforces the CLI's resolved-path contract on the immutable boundary input.
        WHO: Pydantic calls this while the caller creates an assembly configuration.
        WHEN: Before preference lookup, session construction, credential work, or app startup.

        Raises:
            ValueError: If the workdir or supplied workspace file is not absolute.
        """
        if not self.workdir.is_absolute():
            raise ValueError("interactive workdir must be resolved and absolute")
        if self.workspace_file is not None and not self.workspace_file.is_absolute():
            raise ValueError("interactive workspace file must be resolved and absolute")
        return self

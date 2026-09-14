"""Fail-closed persisted trust decisions for project-local plugins."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_warning
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter

__all__ = ["PluginTrustDAO", "PluginTrustStore"]


class PluginTrustDAO(BaseModel):
    """Durable collection of project paths authorized to load local plugins."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    trusted_projects: list[str] = Field(default_factory=list)


class PluginTrustStore:
    """Read and persist project-local plugin authorization decisions.

    WHAT: Enforces consent before project-local Python can load into a session.
    WHO: Consulted by the plugin loader and changed only by an operator action.
    WHEN: During plugin discovery or a `/plugins trust` request.
    """

    def __init__(self, *, store_path: Optional[Path] = None) -> None:
        """Bind the trust store to its durable JSON document.

        Args:
            store_path (Optional[Path]): Test override; defaults to ~/.slo/trust.json.
        """
        self._store_path: Path = store_path or (Path.home() / ".slo" / "trust.json")

    def is_trusted(self, *, project_dir: Path) -> bool:
        """Return whether the resolved project has explicit trust evidence.

        Args:
            project_dir (Path): Project root that owns local plugin files.

        Returns:
            bool: True only for a successfully parsed, recorded resolved path.
        """
        trust: Optional[PluginTrustDAO] = self._load()
        if trust is None:
            return False
        return str(project_dir.resolve()) in trust.trusted_projects

    def trust(self, *, project_dir: Path) -> None:
        """Persist explicit authorization for a project-local plugin directory.

        Args:
            project_dir (Path): Project root the operator trusts.
        """
        trust: PluginTrustDAO = self._load() or PluginTrustDAO()
        resolved_path: str = str(project_dir.resolve())
        if resolved_path not in trust.trusted_projects:
            trust.trusted_projects.append(resolved_path)
        AtomicFileWriter.write_json(path=self._store_path, model=trust)

    def _load(self) -> Optional[PluginTrustDAO]:
        """Load the durable decision set, treating any failure as untrusted.

        Returns:
            Optional[PluginTrustDAO]: Parsed trust decisions, or None on absence/error.
        """
        if not self._store_path.exists():
            return None
        try:
            return PluginTrustDAO.model_validate_json(self._store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log_warning(msg="plugin_trust_load_failed", path=str(self._store_path), error=str(exc))
            return None

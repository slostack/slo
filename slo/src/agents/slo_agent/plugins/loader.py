"""Plugin discovery, trust-gating, and exception-isolated loading (75.a.3/75.a.4).

``PluginLoader`` discovers plugin files across the three trusted tiers —
managed install directory, trusted project directory, and explicit ``--plugin``
paths — imports each under a unique module name, invokes its ``register(slo)``
factory, and isolates every failure into the plugin's health record. A broken
plugin never raises into the session and never affects another plugin.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from collections.abc import Callable
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_warning
from src.agents.slo_agent.plugins.api import PluginAPI
from src.agents.slo_agent.plugins.dao import (
    PluginHealthDAO,
    PluginRegistrationDAO,
    PluginStatus,
)
from src.agents.slo_agent.plugins.trust import PluginTrustStore

__all__ = ["PluginLoader", "PluginLoadResultDAO"]

_PLUGINS_DISABLED_ENV: str = "SLO_PLUGINS_DISABLED"
"""Kill-switch environment variable; ``1`` disables every plugin tier."""

_MANIFEST_FILE_NAME: str = "manifest.json"
"""Manifest written by the installer into each managed plugin directory."""


class PluginLoadResultDAO(BaseModel):
    """Everything one loader pass discovered and loaded.

    Attributes:
        registrations (list[PluginRegistrationDAO]): One registration per
            discovered plugin, in stable discovery order, including
            ``LOAD_FAILED`` records.
        discovered_paths (list[Path]): Entry files discovered across all
            tiers, in the same order as ``registrations``.
    """

    model_config = ConfigDict(extra="forbid")

    registrations: list[PluginRegistrationDAO] = Field(default_factory=list)
    discovered_paths: list[Path] = Field(default_factory=list)


@dataclass(frozen=True)
class _PluginCandidateDAO:
    """One discovered plugin awaiting import.

    Attributes:
        plugin_id (str): Canonical id — the managed directory name for a
            managed plugin, or the file stem for project/CLI plugins.
        entry_path (Path): The Python file to import.
        module_name (str): Unique import root for ``sys.modules`` isolation.
    """

    plugin_id: str
    entry_path: Path
    module_name: str


class PluginLoader:
    """Discover, trust-gate, import, and register plugins for one session.

    WHAT: The single owner of the discover → gate → import → ``register(slo)``
        lifecycle. Every per-plugin step is exception-isolated into health.
    WHO: Invoked once by ``SloAgentSession`` during session construction, and
        again by the ``/plugins reload`` flow.
    WHEN: Before the session processes its first prompt.
    """

    @classmethod
    def load(
        cls,
        *,
        managed_root: Path,
        project_dir: Path,
        trust_store: PluginTrustStore,
        cli_paths: list[Path],
        status_setter: Callable[[str, str], None] | None = None,
    ) -> PluginLoadResultDAO:
        """Load plugins synchronously during session construction.

        WHAT: Runs the file-import portion of plugin loading without event-loop ownership.
        WHO: ``SloAgentSession`` calls it before the first prompt.
        WHEN: Construction or a TUI-triggered reload needs a fresh registry.
        """
        if os.environ.get(_PLUGINS_DISABLED_ENV) == "1":
            return PluginLoadResultDAO()
        candidates: list[_PluginCandidateDAO] = cls._discover_candidates(
            managed_root=managed_root,
            project_dir=project_dir,
            trust_store=trust_store,
            cli_paths=cli_paths,
        )
        registrations: list[PluginRegistrationDAO] = [
            cls._load_one_sync(candidate=candidate, status_setter=status_setter) for candidate in candidates
        ]
        return PluginLoadResultDAO(
            registrations=registrations,
            discovered_paths=[candidate.entry_path for candidate in candidates],
        )

    @classmethod
    async def invoke(
        cls,
        *,
        managed_root: Path,
        project_dir: Path,
        trust_store: PluginTrustStore,
        cli_paths: list[Path],
        status_setter: Callable[[str, str], None] | None = None,
    ) -> PluginLoadResultDAO:
        """Discover and load every plugin visible to this session.

        Honors the ``SLO_PLUGINS_DISABLED=1`` kill switch first, then loads in
        stable tier order: managed directory, trusted project directory,
        explicit CLI paths.

        Args:
            managed_root (Path): Managed plugin root
                (``~/.slo/plugins/plugins`` or a test override).
            project_dir (Path): Session workdir whose ``.slo/plugins`` tier is
                gated by the trust store.
            trust_store (PluginTrustStore): Fail-closed project-trust gate.
            cli_paths (list[Path]): Explicit ``--plugin`` paths, trusted by
                definition, loaded in CLI argument order.
            status_setter (Callable[[str, str], None] | None): Session-owned
                live status-map writer for event-time plugin updates.

        Returns:
            PluginLoadResultDAO: Loaded registrations (including LOAD_FAILED
                records) and the discovered entry paths, in stable order.
        """
        if os.environ.get(_PLUGINS_DISABLED_ENV) == "1":
            return PluginLoadResultDAO()
        candidates: list[_PluginCandidateDAO] = cls._discover_candidates(
            managed_root=managed_root,
            project_dir=project_dir,
            trust_store=trust_store,
            cli_paths=cli_paths,
        )
        registrations: list[PluginRegistrationDAO] = []
        for candidate in candidates:
            registrations.append(await cls._load_one(candidate=candidate, status_setter=status_setter))
        return PluginLoadResultDAO(
            registrations=registrations,
            discovered_paths=[candidate.entry_path for candidate in candidates],
        )

    @classmethod
    def _discover_candidates(
        cls,
        *,
        managed_root: Path,
        project_dir: Path,
        trust_store: PluginTrustStore,
        cli_paths: list[Path],
    ) -> list[_PluginCandidateDAO]:
        """Build the ordered candidate list across all three tiers.

        Args:
            managed_root (Path): Managed plugin root.
            project_dir (Path): Session workdir.
            trust_store (PluginTrustStore): Trust gate for the project tier.
            cli_paths (list[Path]): Explicit CLI paths in argument order.

        Returns:
            list[_PluginCandidateDAO]: Managed candidates (alphabetical), then
                trusted project candidates (alphabetical), then CLI candidates
                in argument order.
        """
        candidates: list[_PluginCandidateDAO] = []
        candidates.extend(cls._discover_managed(managed_root=managed_root))
        candidates.extend(cls._discover_project(project_dir=project_dir, trust_store=trust_store))
        candidates.extend(cls._discover_cli(cli_paths=cli_paths))
        return candidates

    @classmethod
    def _discover_managed(cls, *, managed_root: Path) -> list[_PluginCandidateDAO]:
        """Discover installed plugins in the managed directory tier.

        Args:
            managed_root (Path): Managed plugin root containing one
                ``<plugin-id>/`` directory per installed plugin.

        Returns:
            list[_PluginCandidateDAO]: One candidate per managed directory,
                alphabetical by plugin id. Directories without a manifest are
                still candidates — their load failure is recorded in health.
        """
        if not managed_root.is_dir():
            return []
        candidates: list[_PluginCandidateDAO] = []
        for plugin_dir in sorted(managed_root.iterdir(), key=lambda path: path.name):
            if not plugin_dir.is_dir():
                continue
            plugin_id: str = plugin_dir.name
            candidates.append(
                _PluginCandidateDAO(
                    plugin_id=plugin_id,
                    entry_path=cls._resolve_managed_entry(plugin_dir=plugin_dir),
                    module_name=f"slo_plugin_{plugin_id.replace('-', '_')}",
                )
            )
        return candidates

    @classmethod
    def _resolve_managed_entry(cls, *, plugin_dir: Path) -> Path:
        """Resolve the entry file for one managed plugin from its manifest.

        Args:
            plugin_dir (Path): Managed plugin directory.

        Returns:
            Path: The manifest-declared entry point, or the manifest path
                itself when unreadable so the load failure names the cause.
        """
        manifest_path: Path = plugin_dir / _MANIFEST_FILE_NAME
        try:
            manifest: dict[str, object] = json.loads(manifest_path.read_text(encoding="utf-8"))
            entry_point: object = manifest.get("entry_point")
            if isinstance(entry_point, str) and entry_point:
                return plugin_dir / entry_point
        except (OSError, ValueError) as exc:
            log_warning(
                msg="plugin_managed_manifest_unreadable",
                path=str(manifest_path),
                error=str(exc),
            )
        return manifest_path

    @classmethod
    def _discover_project(
        cls,
        *,
        project_dir: Path,
        trust_store: PluginTrustStore,
    ) -> list[_PluginCandidateDAO]:
        """Discover trusted project-local ``.slo/plugins/*.py`` files.

        Args:
            project_dir (Path): Session workdir.
            trust_store (PluginTrustStore): Fail-closed trust gate.

        Returns:
            list[_PluginCandidateDAO]: Alphabetical candidates, or empty when
                the project is untrusted or has no plugin directory.
        """
        if not trust_store.is_trusted(project_dir=project_dir):
            return []
        plugins_dir: Path = project_dir / ".slo" / "plugins"
        if not plugins_dir.is_dir():
            return []
        candidates: list[_PluginCandidateDAO] = []
        for plugin_file in sorted(plugins_dir.glob("*.py"), key=lambda path: path.name):
            candidates.append(
                _PluginCandidateDAO(
                    plugin_id=plugin_file.stem,
                    entry_path=plugin_file,
                    module_name=f"slo_plugin_{plugin_file.stem.replace('-', '_')}",
                )
            )
        return candidates

    @classmethod
    def _discover_cli(cls, *, cli_paths: list[Path]) -> list[_PluginCandidateDAO]:
        """Build candidates for explicit ``--plugin`` paths (trusted).

        Args:
            cli_paths (list[Path]): Explicit paths in CLI argument order.

        Returns:
            list[_PluginCandidateDAO]: One candidate per path, order preserved.
        """
        return [
            _PluginCandidateDAO(
                plugin_id=path.stem,
                entry_path=path,
                module_name=f"slo_plugin_{path.stem.replace('-', '_')}",
            )
            for path in cli_paths
        ]

    @classmethod
    async def _load_one(
        cls,
        *,
        candidate: _PluginCandidateDAO,
        status_setter: Callable[[str, str], None] | None = None,
    ) -> PluginRegistrationDAO:
        """Import one candidate and invoke its factory, isolating failures.

        Args:
            candidate (_PluginCandidateDAO): The plugin to load.
            status_setter (Callable[[str, str], None] | None): Session-owned
                writer for live status updates.

        Returns:
            PluginRegistrationDAO: The populated registration, or a
                ``LOAD_FAILED`` record when any step raised.
        """
        registration: PluginRegistrationDAO = PluginRegistrationDAO(
            plugin_id=candidate.plugin_id,
            source_path=str(candidate.entry_path),
            health=PluginHealthDAO(
                plugin_id=candidate.plugin_id,
                source_path=str(candidate.entry_path),
            ),
        )
        try:
            module: ModuleType = cls._import_module(candidate=candidate)
            register: Callable[[PluginAPI], object] = cls._require_register(module=module)
            outcome: object = register(PluginAPI(registration=registration, status_setter=status_setter))
            if inspect.isawaitable(outcome):
                await outcome
        except Exception as exc:  # noqa: BLE001 — a plugin must never fail the session
            registration.health.status = PluginStatus.LOAD_FAILED
            registration.health.load_error = f"{type(exc).__name__}: {exc}"
            log_warning(
                msg="plugin_load_failed",
                plugin_id=candidate.plugin_id,
                error=registration.health.load_error,
            )
        return registration

    @classmethod
    def _load_one_sync(
        cls,
        *,
        candidate: _PluginCandidateDAO,
        status_setter: Callable[[str, str], None] | None = None,
    ) -> PluginRegistrationDAO:
        """Import one synchronous plugin factory during session construction.

        WHAT: Records normal registrations while isolating a factory failure.
        WHO: ``load`` calls it for each discovered candidate.
        WHEN: The caller has no event-loop ownership for the session constructor.
        """
        registration = PluginRegistrationDAO(
            plugin_id=candidate.plugin_id,
            source_path=str(candidate.entry_path),
            health=PluginHealthDAO(plugin_id=candidate.plugin_id, source_path=str(candidate.entry_path)),
        )
        try:
            module = cls._import_module(candidate=candidate)
            register = cls._require_register(module=module)
            outcome = register(PluginAPI(registration=registration, status_setter=status_setter))
            if inspect.isawaitable(outcome):
                raise ValueError("async plugin registration requires asynchronous session loading")
        except Exception as exc:  # noqa: BLE001 -- plugins cannot break a session
            registration.health.status = PluginStatus.LOAD_FAILED
            registration.health.load_error = f"{type(exc).__name__}: {exc}"
            log_warning(
                msg="plugin_load_failed", plugin_id=candidate.plugin_id, error=registration.health.load_error
            )
        return registration

    @classmethod
    def _import_module(cls, *, candidate: _PluginCandidateDAO) -> ModuleType:
        """Import one plugin file under its unique module name.

        Args:
            candidate (_PluginCandidateDAO): The plugin to import.

        Returns:
            ModuleType: The executed module, bound in ``sys.modules`` under
                ``candidate.module_name``.

        Raises:
            FileNotFoundError: When the entry file does not exist.
            ValueError: When import machinery cannot build a module spec.
        """
        if not candidate.entry_path.is_file():
            raise FileNotFoundError(f"plugin file not found: {candidate.entry_path}")
        spec = importlib.util.spec_from_file_location(candidate.module_name, candidate.entry_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot build import spec for {candidate.entry_path}")
        module: ModuleType = importlib.util.module_from_spec(spec)
        sys.modules[candidate.module_name] = module
        spec.loader.exec_module(module)
        return module

    @classmethod
    def _require_register(cls, *, module: ModuleType) -> Callable[[PluginAPI], object]:
        """Return the module's ``register`` factory or fail the load.

        Args:
            module (ModuleType): The imported plugin module.

        Returns:
            Callable[[PluginAPI], object]: The typed ``register`` factory.

        Raises:
            ValueError: When the module has no callable ``register``.
        """
        candidate: object = getattr(module, "register", None)
        if not callable(candidate):
            raise ValueError("plugin module has no callable register(slo) factory")
        return candidate

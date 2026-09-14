"""Managed-plugin installation, listing, and removal (feature 75.a.4).

``PluginInstallerService`` is the single writer of ``~/.slo/plugins/``. It
fetches a supported GitHub/GitLab source at a pinned revision, validates its
``slo-plugin.json`` manifest, copies only the declared payload, and swaps it
into place atomically with rollback. The installer **never executes source
code**: the only subprocess it spawns is ``git clone`` / ``git rev-parse``
against the remote.

Rollback-triggering failure set (finding M6(b), interpretation B):
only swap-phase failures (staging build, payload copy, atomic move, registry
write) restore a pre-existing install. Network/clone failures and manifest
validation failures happen before any install is touched, so they never
restore — they leave the machine exactly as it was.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
from src.agents.slo_agent.plugins.identity import PluginIdentityDAO

__all__ = [
    "PluginInstallRecordDAO",
    "PluginInstallRegistryDAO",
    "PluginInstallerService",
    "PluginManifestDAO",
]

_SUPPORTED_HOSTS: tuple[str, ...] = ("github.com", "gitlab.com")
_MANIFEST_SOURCE_NAME: str = "slo-plugin.json"
_MANIFEST_INSTALLED_NAME: str = "manifest.json"
_REGISTRY_FILE_NAME: str = "registry.json"
_STATE_INSTALLED: str = "installed"
_BUNDLED_SOURCE_URL: str = "https://github.com/slo/slo"
_BUNDLED_PLUGIN_ID: str = "slo-slo"
_BUNDLED_PLUGIN_SOURCE_DIR: Path = Path(__file__).parents[4] / "plugins" / "bash_live_output"


class PluginManifestDAO(BaseModel):
    """Validated shape of a plugin repo's ``slo-plugin.json``.

    WHAT: The installer's contract with the source. ``extra="forbid"`` — an
        unrecognized field refuses the install.

    Attributes:
        schema_version (int): Manifest schema version; must be ``1``.
        entry_point (str): Plugin entry file, relative to the payload root.
        payload (list[str]): Files/dirs to copy, relative to the repo root.
        tool_suffixes (list[str]): Local tool-name suffixes the plugin registers.
        command_suffixes (list[str]): Local slash-command suffixes it registers.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    entry_point: str
    payload: list[str] = Field(default_factory=list)
    tool_suffixes: list[str] = Field(default_factory=list)
    command_suffixes: list[str] = Field(default_factory=list)


class PluginInstallRecordDAO(BaseModel):
    """One installed plugin's durable record in the install registry."""

    model_config = ConfigDict(extra="forbid")

    namespace: str
    plugin_id: str
    source_url: str
    pinned_revision: str
    installed_at: str
    state: str = _STATE_INSTALLED
    clone_url: Optional[str] = None


class PluginInstallRegistryDAO(BaseModel):
    """The durable registry of installed managed plugins (``registry.json``)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    plugins: list[PluginInstallRecordDAO] = Field(default_factory=list)


class PluginInstallerService:
    """Own install, list, uninstall, and upgrade of managed plugins.

    WHAT: The only writer of the managed plugin directory. Install is a
        validated, atomic copy — never an execution.
    WHO: Invoked by ``TyperDispatch.plugin`` for every ``slo plugin`` verb.
    WHEN: On an explicit operator command — never during a session run.
    """

    @classmethod
    async def install(
        cls,
        *,
        source_url: str,
        plugins_root: Optional[Path] = None,
        confirmed: bool = False,
        clone_url_override: Optional[str] = None,
    ) -> PluginInstallRecordDAO:
        """Install one plugin from a supported Git URL, atomically.

        Args:
            source_url (str): GitHub/GitLab HTTPS URL.
            plugins_root (Optional[Path]): Override managed root for tests;
                defaults to ``~/.slo/plugins``.
            confirmed (bool): Operator confirmed trust in this source
                (``--yes`` or an interactive confirmation).
            clone_url_override (Optional[str]): Test seam — fetch from this
                URL/path instead of ``source_url`` (identity still derives
                from ``source_url``).

        Returns:
            PluginInstallRecordDAO: The recorded install.

        Raises:
            ValueError: On unsupported URL, invalid manifest, unconfirmed new
                namespace, or a namespace already installed from another
                source or at a different revision (use ``upgrade``).
        """
        identity: PluginIdentityDAO = PluginIdentityDAO.from_source_url(source_url=source_url)
        root: Path = cls._resolve_root(plugins_root=plugins_root)
        registry: PluginInstallRegistryDAO = cls._load_registry(root=root)
        existing: Optional[PluginInstallRecordDAO] = cls._find_record(
            registry=registry, plugin_id=identity.plugin_id
        )
        if existing is not None and existing.source_url != identity.source_url:
            raise ValueError(
                f"plugin id '{identity.plugin_id}' is already installed from "
                f"{existing.source_url}; refusing {identity.source_url}. "
                f"Uninstall the existing plugin first."
            )
        cls._require_confirmation(existing=existing, confirmed=confirmed, identity=identity)
        staged: Path = await cls._fetch_and_stage(
            identity=identity,
            clone_url=clone_url_override or identity.source_url,
        )
        try:
            revision: str = cls._staged_revision(staged=staged)
            if existing is not None and existing.pinned_revision == revision:
                return existing
            if existing is not None:
                raise ValueError(
                    f"plugin '{identity.plugin_id}' is installed at "
                    f"{existing.pinned_revision[:12]}; the source is now at "
                    f"{revision[:12]}. Run `slo plugin upgrade {identity.plugin_id}`."
                )
            record: PluginInstallRecordDAO = PluginInstallRecordDAO(
                namespace=identity.namespace,
                plugin_id=identity.plugin_id,
                source_url=identity.source_url,
                pinned_revision=revision,
                installed_at=datetime.now(tz=timezone.utc).isoformat(),
                clone_url=clone_url_override,
            )
            cls._swap_install_and_write_registry(
                root=root,
                identity=identity,
                staged=staged,
                registry=registry,
                record=record,
            )
            return record
        finally:
            shutil.rmtree(staged.parent, ignore_errors=True)

    @classmethod
    async def install_bundled_bash_live_output(
        cls,
        *,
        plugins_root: Optional[Path] = None,
    ) -> PluginInstallRecordDAO:
        """Install Slo's bundled Bash renderer through the managed directory path.

        WHAT: Copies the release-bundled payload into the same managed layout and
            writes the same install registry used by remote plugins. Its immutable
            provenance is the packaged Slo source URL plus the installed package
            version, because no remote clone is required (M4).
        WHO: Release/bootstrap callers may invoke this explicit delivery seam.
        WHEN: After Slo itself is installed, never during normal plugin loading.

        Args:
            plugins_root (Optional[Path]): Managed-root test override.

        Returns:
            PluginInstallRecordDAO: Idempotent bundled-plugin install record.

        Raises:
            ValueError: When the bundled manifest or payload is unavailable.
        """
        root: Path = cls._resolve_root(plugins_root=plugins_root)
        registry: PluginInstallRegistryDAO = cls._load_registry(root=root)
        existing: Optional[PluginInstallRecordDAO] = cls._find_record(
            registry=registry,
            plugin_id=_BUNDLED_PLUGIN_ID,
        )
        if existing is not None:
            return existing
        identity: PluginIdentityDAO = PluginIdentityDAO.from_source_url(source_url=_BUNDLED_SOURCE_URL)
        manifest: PluginManifestDAO = cls._read_manifest(clone_dir=_BUNDLED_PLUGIN_SOURCE_DIR)
        staging_parent: Path = Path(tempfile.mkdtemp(prefix="slo-bundled-plugin-stage-"))
        staged: Path = staging_parent / identity.plugin_id
        staged.mkdir()
        try:
            cls._copy_payload(
                clone_dir=_BUNDLED_PLUGIN_SOURCE_DIR,
                manifest=manifest,
                staged=staged,
            )
            AtomicFileWriter.write_json(path=staged / _MANIFEST_INSTALLED_NAME, model=manifest)
            record: PluginInstallRecordDAO = PluginInstallRecordDAO(
                namespace=identity.namespace,
                plugin_id=identity.plugin_id,
                source_url=identity.source_url,
                pinned_revision=cls._bundled_revision(),
                installed_at=datetime.now(tz=timezone.utc).isoformat(),
            )
            cls._swap_install_and_write_registry(
                root=root,
                identity=identity,
                staged=staged,
                registry=registry,
                record=record,
            )
            return record
        finally:
            shutil.rmtree(staging_parent, ignore_errors=True)

    @classmethod
    async def list_installed(cls, *, plugins_root: Optional[Path] = None) -> list[PluginInstallRecordDAO]:
        """Return every recorded install, in registry order.

        Args:
            plugins_root (Optional[Path]): Override managed root for tests.

        Returns:
            list[PluginInstallRecordDAO]: All installed plugin records.
        """
        root: Path = cls._resolve_root(plugins_root=plugins_root)
        return list(cls._load_registry(root=root).plugins)

    @classmethod
    async def uninstall(cls, *, plugin_id: str, plugins_root: Optional[Path] = None) -> None:
        """Remove one installed plugin and its registry record.

        Args:
            plugin_id (str): The plugin id to remove.
            plugins_root (Optional[Path]): Override managed root for tests.

        Raises:
            ValueError: When no plugin with that id is installed.
        """
        root: Path = cls._resolve_root(plugins_root=plugins_root)
        registry: PluginInstallRegistryDAO = cls._load_registry(root=root)
        record: Optional[PluginInstallRecordDAO] = cls._find_record(registry=registry, plugin_id=plugin_id)
        if record is None:
            raise ValueError(f"plugin '{plugin_id}' is not installed")
        shutil.rmtree(root / "plugins" / plugin_id, ignore_errors=True)
        registry.plugins = [entry for entry in registry.plugins if entry.plugin_id != plugin_id]
        cls._write_registry(root=root, registry=registry)

    @classmethod
    async def upgrade(cls, *, plugin_id: str, plugins_root: Optional[Path] = None) -> PluginInstallRecordDAO:
        """Re-fetch one plugin at its source's newest commit and swap atomically.

        Only swap-phase failures restore the previous install (M6(b)); a
        fetch/clone or manifest failure never touches the existing install.

        Args:
            plugin_id (str): The installed plugin id to upgrade.
            plugins_root (Optional[Path]): Override managed root for tests.

        Returns:
            PluginInstallRecordDAO: The updated record with the new pin.

        Raises:
            ValueError: When the plugin is not installed.
        """
        root: Path = cls._resolve_root(plugins_root=plugins_root)
        registry: PluginInstallRegistryDAO = cls._load_registry(root=root)
        existing: Optional[PluginInstallRecordDAO] = cls._find_record(registry=registry, plugin_id=plugin_id)
        if existing is None:
            raise ValueError(f"plugin '{plugin_id}' is not installed")
        identity: PluginIdentityDAO = PluginIdentityDAO.from_source_url(source_url=existing.source_url)
        staged: Path = await cls._fetch_and_stage(
            identity=identity,
            clone_url=existing.clone_url or existing.source_url,
        )
        try:
            revision: str = cls._staged_revision(staged=staged)
            record: PluginInstallRecordDAO = existing.model_copy(
                update={
                    "pinned_revision": revision,
                    "installed_at": datetime.now(tz=timezone.utc).isoformat(),
                }
            )
            cls._swap_upgrade_and_write_registry(
                root=root,
                identity=identity,
                staged=staged,
                registry=registry,
                record=record,
            )
            return record
        finally:
            shutil.rmtree(staged.parent, ignore_errors=True)

    # ---- Fetch and stage (pre-swap; failures never touch installs) -----------

    @classmethod
    async def _fetch_and_stage(cls, *, identity: PluginIdentityDAO, clone_url: str) -> Path:
        """Clone at a pinned revision and stage a validated payload copy.

        Args:
            identity (PluginIdentityDAO): Derived identity for the plugin.
            clone_url (str): URL or local path to clone from.

        Returns:
            Path: The staged payload directory (``<tmp>/<plugin-id>``).

        Raises:
            RuntimeError: When the clone or revision resolution fails.
            ValueError: When the manifest is missing, invalid, or declares a
                payload path that escapes the repository root.
        """
        staging_parent: Path = Path(tempfile.mkdtemp(prefix="slo-plugin-stage-"))
        clone_dir: Path = staging_parent / "clone"
        await cls._git_clone(clone_url=clone_url, destination=clone_dir)
        revision: str = await cls._resolve_revision(clone_dir=clone_dir)
        (staging_parent / "REVISION").write_text(revision, encoding="utf-8")
        manifest: PluginManifestDAO = cls._read_manifest(clone_dir=clone_dir)
        staged: Path = staging_parent / identity.plugin_id
        staged.mkdir()
        cls._copy_payload(clone_dir=clone_dir, manifest=manifest, staged=staged)
        AtomicFileWriter.write_json(path=staged / _MANIFEST_INSTALLED_NAME, model=manifest)
        return staged

    @classmethod
    async def _git_clone(cls, *, clone_url: str, destination: Path) -> None:
        """Clone the remote shallowly into ``destination``.

        Args:
            clone_url (str): URL or path to clone.
            destination (Path): Target directory for the clone.

        Raises:
            RuntimeError: When git exits non-zero.
        """
        process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
            "git",
            "clone",
            "--quiet",
            clone_url,
            str(destination),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"git clone failed for {clone_url}: {stderr.decode(errors='replace').strip()}")

    @classmethod
    async def _resolve_revision(cls, *, clone_dir: Path) -> str:
        """Pin the exact commit SHA the clone resolved to via ``git rev-parse``.

        Args:
            clone_dir (Path): The cloned repository root.

        Returns:
            str: The full HEAD commit SHA.

        Raises:
            RuntimeError: When git exits non-zero.
        """
        process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            "HEAD",
            cwd=clone_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"git rev-parse failed: {stderr.decode(errors='replace').strip()}")
        return stdout.decode().strip()

    @classmethod
    def _read_manifest(cls, *, clone_dir: Path) -> PluginManifestDAO:
        """Read and validate the clone's ``slo-plugin.json``.

        Args:
            clone_dir (Path): The cloned repository root.

        Returns:
            PluginManifestDAO: The validated manifest.

        Raises:
            ValueError: When the manifest is absent, unparseable, fails
                validation, or is not schema version 1.
        """
        manifest_path: Path = clone_dir / _MANIFEST_SOURCE_NAME
        try:
            raw: str = manifest_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"plugin source has no readable {_MANIFEST_SOURCE_NAME}") from exc
        try:
            manifest: PluginManifestDAO = PluginManifestDAO.model_validate_json(raw)
        except ValueError as exc:
            raise ValueError(f"invalid {_MANIFEST_SOURCE_NAME}: {exc}") from exc
        if manifest.schema_version != 1:
            raise ValueError(f"unsupported manifest schema_version: {manifest.schema_version}")
        return manifest

    @classmethod
    def _copy_payload(cls, *, clone_dir: Path, manifest: PluginManifestDAO, staged: Path) -> None:
        """Copy exactly the declared payload into the staging directory.

        Args:
            clone_dir (Path): The cloned repository root.
            manifest (PluginManifestDAO): The validated manifest.
            staged (Path): The staging payload directory.

        Raises:
            ValueError: When a payload path escapes the repository root or a
                declared payload entry does not exist.
        """
        for relative in manifest.payload:
            source: Path = (clone_dir / relative).resolve()
            if not source.is_relative_to(clone_dir.resolve()):
                raise ValueError(f"payload path escapes the repository root: {relative}")
            if not source.exists():
                raise ValueError(f"declared payload entry does not exist: {relative}")
            destination: Path = staged / relative
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        entry: Path = staged / manifest.entry_point
        if not entry.exists():
            raise ValueError(f"manifest entry_point not in payload: {manifest.entry_point}")

    @classmethod
    def _staged_revision(cls, *, staged: Path) -> str:
        """Resolve the pinned commit SHA recorded alongside the staged payload.

        Args:
            staged (Path): The staged payload directory.

        Returns:
            str: The full commit SHA the clone resolved to.
        """
        revision_file: Path = staged.parent / "REVISION"
        return revision_file.read_text(encoding="utf-8").strip()

    # ---- Swap phase (failures here restore the previous install — M6(b)) -----

    @classmethod
    def _swap_install_and_write_registry(
        cls,
        *,
        root: Path,
        identity: PluginIdentityDAO,
        staged: Path,
        registry: PluginInstallRegistryDAO,
        record: PluginInstallRecordDAO,
    ) -> None:
        """Swap a new payload into place only when its registry write succeeds.

        WHAT: Makes a new managed directory and its registry record one durable
            unit. A post-swap registry failure removes the just-installed payload.
        WHO: Called only by ``install`` after source validation succeeds.
        WHEN: In the installation swap phase, immediately before success returns.

        Args:
            root (Path): Managed plugins root.
            identity (PluginIdentityDAO): Directory identity for the payload.
            staged (Path): Fully validated staged payload directory.
            registry (PluginInstallRegistryDAO): Current registry model.
            record (PluginInstallRecordDAO): New durable install record.

        Raises:
            OSError: When payload swap or registry persistence fails.
        """
        managed: Path = root / "plugins"
        managed.mkdir(parents=True, exist_ok=True)
        destination: Path = managed / identity.plugin_id
        previous_records: list[PluginInstallRecordDAO] = list(registry.plugins)
        try:
            shutil.move(str(staged), str(destination))
            registry.plugins.append(record)
            cls._write_registry(root=root, registry=registry)
        except OSError:
            shutil.rmtree(destination, ignore_errors=True)
            registry.plugins = previous_records
            raise

    @classmethod
    def _swap_upgrade_and_write_registry(
        cls,
        *,
        root: Path,
        identity: PluginIdentityDAO,
        staged: Path,
        registry: PluginInstallRegistryDAO,
        record: PluginInstallRecordDAO,
    ) -> None:
        """Swap an upgrade payload and persist its new pin as one rollback unit.

        WHAT: Replaces an existing managed payload only while its replacement
            registry record can be persisted. A registry-write failure restores
            both the old payload and the in-memory registry list.
        WHO: Called only by ``upgrade`` after clone and manifest validation.
        WHEN: In the upgrade swap phase, after pre-swap failures can no longer
            alter the existing install.

        Args:
            root (Path): Managed plugins root.
            identity (PluginIdentityDAO): Directory identity for the payload.
            staged (Path): Fully validated staged payload directory.
            registry (PluginInstallRegistryDAO): Current durable registry model.
            record (PluginInstallRecordDAO): Replacement registry record.

        Raises:
            OSError: When payload swap or registry persistence fails after the
                previous payload has been restored where possible.
        """
        managed: Path = root / "plugins"
        managed.mkdir(parents=True, exist_ok=True)
        destination: Path = managed / identity.plugin_id
        backup: Path = managed / f".{identity.plugin_id}.backup"
        previous_records: list[PluginInstallRecordDAO] = list(registry.plugins)
        shutil.rmtree(backup, ignore_errors=True)
        if destination.exists():
            destination.replace(backup)
        try:
            shutil.move(str(staged), str(destination))
            registry.plugins = [
                record if entry.plugin_id == identity.plugin_id else entry for entry in registry.plugins
            ]
            cls._write_registry(root=root, registry=registry)
        except OSError:
            shutil.rmtree(destination, ignore_errors=True)
            if backup.exists():
                backup.replace(destination)
            registry.plugins = previous_records
            raise
        shutil.rmtree(backup, ignore_errors=True)

    @classmethod
    def _swap_into_place(cls, *, root: Path, identity: PluginIdentityDAO, staged: Path) -> None:
        """Atomically move the staged payload into the managed directory.

        A pre-existing install is moved aside first and restored when the swap
        fails (rollback-triggering set, M6(b): swap-phase failures only).

        Args:
            root (Path): Managed plugins root.
            identity (PluginIdentityDAO): Plugin identity naming the directory.
            staged (Path): The staged payload directory.

        Raises:
            OSError: When the swap fails after a successful rollback.
        """
        managed: Path = root / "plugins"
        managed.mkdir(parents=True, exist_ok=True)
        destination: Path = managed / identity.plugin_id
        backup: Path = managed / f".{identity.plugin_id}.backup"
        shutil.rmtree(backup, ignore_errors=True)
        had_previous: bool = destination.exists()
        if had_previous:
            destination.replace(backup)
        try:
            shutil.move(str(staged), str(destination))
        except OSError:
            if had_previous and backup.exists():
                backup.replace(destination)
            raise
        shutil.rmtree(backup, ignore_errors=True)

    # ---- Registry I/O ---------------------------------------------------------

    @classmethod
    def _record_install(
        cls,
        *,
        root: Path,
        registry: PluginInstallRegistryDAO,
        record: PluginInstallRecordDAO,
    ) -> None:
        """Append one install record to the durable registry.

        Args:
            root (Path): Managed plugins root.
            registry (PluginInstallRegistryDAO): The loaded registry.
            record (PluginInstallRecordDAO): The new record.
        """
        registry.plugins.append(record)
        cls._write_registry(root=root, registry=registry)

    @classmethod
    def _load_registry(cls, *, root: Path) -> PluginInstallRegistryDAO:
        """Load the install registry, tolerating absence.

        Args:
            root (Path): Managed plugins root.

        Returns:
            PluginInstallRegistryDAO: Parsed registry, or an empty one.

        Raises:
            ValueError: When the registry file exists but is corrupt.
        """
        registry_path: Path = root / _REGISTRY_FILE_NAME
        if not registry_path.exists():
            return PluginInstallRegistryDAO()
        try:
            return PluginInstallRegistryDAO.model_validate_json(registry_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"corrupt plugin install registry: {registry_path}") from exc

    @classmethod
    def _write_registry(cls, *, root: Path, registry: PluginInstallRegistryDAO) -> None:
        """Persist the registry through the shared atomic writer.

        Args:
            root (Path): Managed plugins root.
            registry (PluginInstallRegistryDAO): The registry to persist.
        """
        AtomicFileWriter.write_json(path=root / _REGISTRY_FILE_NAME, model=registry)

    # ---- Small helpers ---------------------------------------------------------

    @classmethod
    def _bundled_revision(cls) -> str:
        """Return immutable installed-package provenance for the bundled payload.

        Returns:
            str: Installed Slo distribution version, prefixed to distinguish it
                from a remote Git SHA in the same registry field.
        """
        try:
            from importlib.metadata import version

            return f"package:{version('slo')}"
        except Exception:  # noqa: BLE001 -- editable checkout fallback
            return "package:development"

    @classmethod
    def _resolve_root(cls, *, plugins_root: Optional[Path]) -> Path:
        """Resolve the managed plugins root.

        Args:
            plugins_root (Optional[Path]): Explicit override, or None for the
                user-global default.

        Returns:
            Path: The managed root (``~/.slo/plugins`` by default).
        """
        return plugins_root if plugins_root is not None else Path.home() / ".slo" / "plugins"

    @classmethod
    def _find_record(
        cls, *, registry: PluginInstallRegistryDAO, plugin_id: str
    ) -> Optional[PluginInstallRecordDAO]:
        """Find one record by plugin id.

        Args:
            registry (PluginInstallRegistryDAO): The loaded registry.
            plugin_id (str): The plugin id to find.

        Returns:
            Optional[PluginInstallRecordDAO]: The record, or None.
        """
        for entry in registry.plugins:
            if entry.plugin_id == plugin_id:
                return entry
        return None

    @classmethod
    def _require_confirmation(
        cls,
        *,
        existing: Optional[PluginInstallRecordDAO],
        confirmed: bool,
        identity: PluginIdentityDAO,
    ) -> None:
        """Require operator confirmation before installing a new namespace.

        Args:
            existing (Optional[PluginInstallRecordDAO]): Current install, if any.
            confirmed (bool): Whether the operator confirmed the install.
            identity (PluginIdentityDAO): The plugin being installed.

        Raises:
            ValueError: When a new namespace is installed unconfirmed.
        """
        if existing is not None or confirmed:
            return
        raise ValueError(
            f"installing '{identity.plugin_id}' from {identity.source_url} requires "
            "operator confirmation; re-run with --yes to confirm you trust this source"
        )

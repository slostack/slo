"""Tests for plugin discovery and exception-isolated loading (75.a.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.slo_agent.plugins.dao import PluginStatus
from src.agents.slo_agent.plugins.loader import PluginLoader, PluginLoadResultDAO
from src.agents.slo_agent.plugins.trust import PluginTrustStore

_REGISTER_SYNC: str = (
    "def register(slo):\n"
    "    slo.on(event_kind='run_completed', handler=lambda event: None)\n"
    "    slo.set_status(key='alpha:status', text='ready')\n"
)

_REGISTER_ASYNC: str = (
    "async def register(slo):\n" "    slo.register_command(name='beta:hi', handler=lambda: 'hi')\n"
)

_RAISING_REGISTER: str = "def register(slo):\n    raise RuntimeError('boom')\n"

_NO_REGISTER: str = "VALUE = 42\n"


def _write_plugin(*, directory: Path, name: str, body: str) -> Path:
    """Write one plugin file into ``directory``.

    Args:
        directory (Path): Directory that must already exist.
        name (str): File name including the ``.py`` suffix.
        body (str): Python source for the plugin file.

    Returns:
        Path: The written plugin file path.
    """
    path: Path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def _write_managed_plugin(*, managed_root: Path, plugin_id: str, body: str) -> Path:
    """Write one managed-tier plugin directory with manifest and entry file.

    Args:
        managed_root (Path): Managed ``plugins/plugins`` root override.
        plugin_id (str): Managed plugin directory name (the canonical id).
        body (str): Python source for the plugin entry file.

    Returns:
        Path: The managed plugin directory.
    """
    plugin_dir: Path = managed_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        '{"schema_version": 1, "entry_point": "plugin.py", "payload": ["plugin.py"]}',
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(body, encoding="utf-8")
    return plugin_dir


class TestPluginLoadResultDAO:
    """The load result carries registrations plus discovered paths."""

    def test_defaults_construct_empty_result(self) -> None:
        """An empty result is valid and reports no loaded plugins."""
        result: PluginLoadResultDAO = PluginLoadResultDAO()

        assert result.registrations == []
        assert result.discovered_paths == []

    def test_result_forbids_extra_fields(self) -> None:
        """The result DAO refuses undeclared fields."""
        with pytest.raises(ValueError):
            PluginLoadResultDAO.model_validate({"registrations": [], "surprise": 1})


class TestDiscoveryOrdering:
    """Discovery returns managed, then project, then CLI paths, alphabetically."""

    @pytest.mark.asyncio
    async def test_discovery_order_is_managed_project_cli(self, tmp_path: Path) -> None:
        """The three tiers concatenate in spec order, alphabetical within each."""
        managed_root: Path = tmp_path / "home" / "plugins" / "plugins"
        project_dir: Path = tmp_path / "project"
        project_plugins: Path = project_dir / ".slo" / "plugins"
        project_plugins.mkdir(parents=True)
        trust_store: PluginTrustStore = PluginTrustStore(store_path=tmp_path / "trust.json")
        trust_store.trust(project_dir=project_dir)

        _write_managed_plugin(managed_root=managed_root, plugin_id="zeta-tools", body=_REGISTER_SYNC)
        _write_managed_plugin(managed_root=managed_root, plugin_id="alpha-tools", body=_REGISTER_SYNC)
        _write_plugin(directory=project_plugins, name="b_proj.py", body=_REGISTER_SYNC)
        _write_plugin(directory=project_plugins, name="a_proj.py", body=_REGISTER_SYNC)
        cli_path: Path = _write_plugin(directory=tmp_path, name="cli_one.py", body=_REGISTER_SYNC)

        result: PluginLoadResultDAO = await PluginLoader.invoke(
            managed_root=managed_root,
            project_dir=project_dir,
            trust_store=trust_store,
            cli_paths=[cli_path],
        )

        stems: list[str] = [path.stem for path in result.discovered_paths]
        assert stems == ["plugin", "plugin", "a_proj", "b_proj", "cli_one"]
        plugin_ids: list[str] = [registration.plugin_id for registration in result.registrations]
        assert plugin_ids == ["alpha-tools", "zeta-tools", "a_proj", "b_proj", "cli_one"]

    @pytest.mark.asyncio
    async def test_untrusted_project_tier_is_skipped(self, tmp_path: Path) -> None:
        """Project plugins never load when the project is not in the trust store."""
        project_dir: Path = tmp_path / "project"
        project_plugins: Path = project_dir / ".slo" / "plugins"
        project_plugins.mkdir(parents=True)
        _write_plugin(directory=project_plugins, name="sneaky.py", body=_REGISTER_SYNC)
        trust_store: PluginTrustStore = PluginTrustStore(store_path=tmp_path / "trust.json")

        result: PluginLoadResultDAO = await PluginLoader.invoke(
            managed_root=tmp_path / "absent-managed",
            project_dir=project_dir,
            trust_store=trust_store,
            cli_paths=[],
        )

        assert result.registrations == []
        assert result.discovered_paths == []

    @pytest.mark.asyncio
    async def test_kill_switch_returns_empty_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SLO_PLUGINS_DISABLED=1 disables every tier, including trusted CLI paths."""
        monkeypatch.setenv("SLO_PLUGINS_DISABLED", "1")
        cli_path: Path = _write_plugin(directory=tmp_path, name="cli_one.py", body=_REGISTER_SYNC)

        result: PluginLoadResultDAO = await PluginLoader.invoke(
            managed_root=tmp_path,
            project_dir=tmp_path,
            trust_store=PluginTrustStore(store_path=tmp_path / "trust.json"),
            cli_paths=[cli_path],
        )

        assert result.registrations == []
        assert result.discovered_paths == []


class TestFactoryInvocation:
    """Sync and async factories both run; failures isolate into health."""

    @pytest.mark.asyncio
    async def test_sync_factory_registers_handlers_and_status(self, tmp_path: Path) -> None:
        """A sync ``register(slo)`` records its registrations."""
        cli_path: Path = _write_plugin(directory=tmp_path, name="alpha.py", body=_REGISTER_SYNC)

        result: PluginLoadResultDAO = await PluginLoader.invoke(
            managed_root=tmp_path / "absent",
            project_dir=tmp_path / "absent",
            trust_store=PluginTrustStore(store_path=tmp_path / "trust.json"),
            cli_paths=[cli_path],
        )

        registration = result.registrations[0]
        assert registration.plugin_id == "alpha"
        assert registration.health.status is PluginStatus.LOADED
        assert registration.health.subscribed_events == ["run_completed"]
        assert registration.statuses == {"alpha:status": "ready"}

    @pytest.mark.asyncio
    async def test_async_factory_is_awaited(self, tmp_path: Path) -> None:
        """An async ``register(slo)`` is awaited before the session starts."""
        cli_path: Path = _write_plugin(directory=tmp_path, name="beta.py", body=_REGISTER_ASYNC)

        result: PluginLoadResultDAO = await PluginLoader.invoke(
            managed_root=tmp_path / "absent",
            project_dir=tmp_path / "absent",
            trust_store=PluginTrustStore(store_path=tmp_path / "trust.json"),
            cli_paths=[cli_path],
        )

        registration = result.registrations[0]
        assert registration.health.status is PluginStatus.LOADED
        assert "beta:hi" in registration.commands

    @pytest.mark.asyncio
    async def test_raising_factory_yields_load_failed_and_other_plugins_load(self, tmp_path: Path) -> None:
        """A raising factory records LOAD_FAILED and never aborts other plugins."""
        bad_path: Path = _write_plugin(directory=tmp_path, name="a_bad.py", body=_RAISING_REGISTER)
        good_path: Path = _write_plugin(directory=tmp_path, name="b_good.py", body=_REGISTER_SYNC)

        result: PluginLoadResultDAO = await PluginLoader.invoke(
            managed_root=tmp_path / "absent",
            project_dir=tmp_path / "absent",
            trust_store=PluginTrustStore(store_path=tmp_path / "trust.json"),
            cli_paths=[bad_path, good_path],
        )

        assert len(result.registrations) == 2
        bad, good = result.registrations
        assert bad.health.status is PluginStatus.LOAD_FAILED
        assert bad.health.load_error is not None
        assert "boom" in bad.health.load_error
        assert good.health.status is PluginStatus.LOADED

    @pytest.mark.asyncio
    async def test_module_without_register_yields_load_failed(self, tmp_path: Path) -> None:
        """A module with no ``register`` attribute records a clear LOAD_FAILED."""
        cli_path: Path = _write_plugin(directory=tmp_path, name="empty.py", body=_NO_REGISTER)

        result: PluginLoadResultDAO = await PluginLoader.invoke(
            managed_root=tmp_path / "absent",
            project_dir=tmp_path / "absent",
            trust_store=PluginTrustStore(store_path=tmp_path / "trust.json"),
            cli_paths=[cli_path],
        )

        registration = result.registrations[0]
        assert registration.health.status is PluginStatus.LOAD_FAILED
        assert registration.health.load_error is not None
        assert "register" in registration.health.load_error

    @pytest.mark.asyncio
    async def test_syntax_error_file_yields_load_failed(self, tmp_path: Path) -> None:
        """An unimportable file records LOAD_FAILED without raising."""
        cli_path: Path = _write_plugin(directory=tmp_path, name="broken.py", body="def broken(:\n")

        result: PluginLoadResultDAO = await PluginLoader.invoke(
            managed_root=tmp_path / "absent",
            project_dir=tmp_path / "absent",
            trust_store=PluginTrustStore(store_path=tmp_path / "trust.json"),
            cli_paths=[cli_path],
        )

        assert result.registrations[0].health.status is PluginStatus.LOAD_FAILED

    @pytest.mark.asyncio
    async def test_missing_cli_file_yields_load_failed(self, tmp_path: Path) -> None:
        """A nonexistent explicit path records LOAD_FAILED rather than raising."""
        result: PluginLoadResultDAO = await PluginLoader.invoke(
            managed_root=tmp_path / "absent",
            project_dir=tmp_path / "absent",
            trust_store=PluginTrustStore(store_path=tmp_path / "trust.json"),
            cli_paths=[tmp_path / "does_not_exist.py"],
        )

        assert result.registrations[0].health.status is PluginStatus.LOAD_FAILED


class TestManagedTierImportIdentity:
    """Managed plugins import under their unique derived module name."""

    @pytest.mark.asyncio
    async def test_managed_plugin_imports_under_unique_module_name(self, tmp_path: Path) -> None:
        """A managed plugin's module lands in ``sys.modules`` under ``slo_plugin_<snake>``."""
        import sys

        managed_root: Path = tmp_path / "plugins" / "plugins"
        _write_managed_plugin(managed_root=managed_root, plugin_id="acme-deploy-tools", body=_REGISTER_SYNC)

        result: PluginLoadResultDAO = await PluginLoader.invoke(
            managed_root=managed_root,
            project_dir=tmp_path / "absent",
            trust_store=PluginTrustStore(store_path=tmp_path / "trust.json"),
            cli_paths=[],
        )

        assert result.registrations[0].plugin_id == "acme-deploy-tools"
        assert result.registrations[0].health.status is PluginStatus.LOADED
        assert "slo_plugin_acme_deploy_tools" in sys.modules

    @pytest.mark.asyncio
    async def test_managed_plugin_with_invalid_manifest_yields_load_failed(self, tmp_path: Path) -> None:
        """A managed dir whose manifest is unreadable records LOAD_FAILED."""
        plugin_dir: Path = tmp_path / "plugins" / "plugins" / "bad-tools"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "manifest.json").write_text("{not json", encoding="utf-8")

        result: PluginLoadResultDAO = await PluginLoader.invoke(
            managed_root=tmp_path / "plugins" / "plugins",
            project_dir=tmp_path / "absent",
            trust_store=PluginTrustStore(store_path=tmp_path / "trust.json"),
            cli_paths=[],
        )

        registration = result.registrations[0]
        assert registration.plugin_id == "bad-tools"
        assert registration.health.status is PluginStatus.LOAD_FAILED

    @pytest.mark.asyncio
    async def test_two_plugins_never_clobber_sys_modules(self, tmp_path: Path) -> None:
        """Two plugins exporting the same module-level names stay isolated."""
        import sys

        managed_root: Path = tmp_path / "plugins" / "plugins"
        _write_managed_plugin(
            managed_root=managed_root,
            plugin_id="one-tools",
            body="MARKER = 'one'\n" + _REGISTER_SYNC,
        )
        _write_managed_plugin(
            managed_root=managed_root,
            plugin_id="two-tools",
            body="MARKER = 'two'\n" + _REGISTER_SYNC,
        )

        await PluginLoader.invoke(
            managed_root=managed_root,
            project_dir=tmp_path / "absent",
            trust_store=PluginTrustStore(store_path=tmp_path / "trust.json"),
            cli_paths=[],
        )

        assert sys.modules["slo_plugin_one_tools"].MARKER == "one"
        assert sys.modules["slo_plugin_two_tools"].MARKER == "two"

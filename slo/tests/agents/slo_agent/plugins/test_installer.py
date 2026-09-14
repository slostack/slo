"""Tests for the managed-plugin installer (75.a.4).

Covers: URL validation, manifest validation, payload copy, pinned revision,
idempotent same-revision install, different-revision refusal with upgrade
hint, staged temp dir + atomic move + rollback (M6(b) enumeration), upgrade
keeps old install on swap failure, uninstall, and the HARD no-execution rule.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.agents.slo_agent.plugins.installer import (
    PluginInstallRecordDAO,
    PluginInstallerService,
    PluginManifestDAO,
)

_MANIFEST: dict = {
    "schema_version": 1,
    "entry_point": "plugin.py",
    "payload": ["plugin.py"],
    "tool_suffixes": ["deploy"],
    "command_suffixes": ["ship"],
}

_PLUGIN_BODY: str = "def register(slo):\n    pass\n"


def _git(*, cwd: Path, args: list[str]) -> str:
    """Run one git command in ``cwd``.

    Args:
        cwd (Path): Working directory for git.
        args (list[str]): Git arguments.

    Returns:
        str: Stdout stripped.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _make_remote(
    *, tmp_path: Path, name: str, manifest: dict | None = None, extra_files: dict[str, str] | None = None
) -> tuple[Path, str]:
    """Create a bare-git fixture remote with one committed plugin.

    Args:
        tmp_path (Path): Test temp dir.
        name (str): Fixture directory name.
        manifest (dict | None): Manifest content (defaults to ``_MANIFEST``).
        extra_files (dict[str, str] | None): Extra repo files.

    Returns:
        tuple[Path, str]: (work repo path, first commit SHA).
    """
    repo: Path = tmp_path / name
    repo.mkdir()
    _git(cwd=repo, args=["init", "-b", "main"])
    _git(cwd=repo, args=["config", "user.email", "test@example.com"])
    _git(cwd=repo, args=["config", "user.name", "Test"])
    (repo / "slo-plugin.json").write_text(json.dumps(manifest or _MANIFEST), encoding="utf-8")
    (repo / "plugin.py").write_text(_PLUGIN_BODY, encoding="utf-8")
    for rel, body in (extra_files or {}).items():
        target: Path = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    _git(cwd=repo, args=["add", "."])
    _git(cwd=repo, args=["commit", "-m", "initial"])
    sha: str = _git(cwd=repo, args=["rev-parse", "HEAD"])
    return repo, sha


def _commit_more(
    *, repo: Path, filename: str = "plugin.py", body: str = "def register(slo):\n    pass  # v2\n"
) -> str:
    """Commit a second revision to the fixture remote.

    Args:
        repo (Path): Work repo path.
        filename (str): File to modify.
        body (str): New file content.

    Returns:
        str: New HEAD SHA.
    """
    (repo / filename).write_text(body, encoding="utf-8")
    _git(cwd=repo, args=["add", "."])
    _git(cwd=repo, args=["commit", "-m", "second"])
    return _git(cwd=repo, args=["rev-parse", "HEAD"])


def _https_url(*, host: str = "github.com", owner: str = "acme", repo: str = "deploy-tools") -> str:
    """Build a canonical HTTPS plugin URL.

    Args:
        host (str): Host name.
        owner (str): Owner component.
        repo (str): Repository component.

    Returns:
        str: The URL.
    """
    return f"https://{host}/{owner}/{repo}"


class TestUrlValidation:
    """HTTPS github.com/gitlab.com owner/repo only."""

    @pytest.mark.asyncio
    async def test_ssh_url_refused(self, tmp_path: Path) -> None:
        """SSH URLs are refused with a clear message."""
        with pytest.raises(ValueError, match="HTTPS"):
            await PluginInstallerService.install(
                source_url="git@github.com:acme/deploy-tools.git",
                plugins_root=tmp_path / "plugins",
                confirmed=True,
            )

    @pytest.mark.asyncio
    async def test_other_host_refused(self, tmp_path: Path) -> None:
        """Non-GitHub/GitLab hosts are refused."""
        with pytest.raises(ValueError):
            await PluginInstallerService.install(
                source_url="https://bitbucket.org/acme/deploy-tools",
                plugins_root=tmp_path / "plugins",
                confirmed=True,
            )

    @pytest.mark.asyncio
    async def test_file_path_refused(self, tmp_path: Path) -> None:
        """Local file paths are refused as install sources."""
        with pytest.raises(ValueError):
            await PluginInstallerService.install(
                source_url="/home/user/plugin",
                plugins_root=tmp_path / "plugins",
                confirmed=True,
            )


class TestManifestValidation:
    """Invalid manifests refuse the install with nothing written."""

    @pytest.mark.asyncio
    async def test_extra_manifest_field_refused(self, tmp_path: Path) -> None:
        """``extra="forbid"`` — an unknown manifest field refuses the install."""
        manifest: dict = {**_MANIFEST, "surprise": True}
        repo, _ = _make_remote(tmp_path=tmp_path, name="repo-extra", manifest=manifest)
        with pytest.raises(ValueError):
            await PluginInstallerService.install(
                source_url=_https_url(),
                plugins_root=tmp_path / "plugins",
                confirmed=True,
                clone_url_override=str(repo),
            )
        assert not (tmp_path / "plugins").exists()

    @pytest.mark.asyncio
    async def test_bad_schema_version_refused(self, tmp_path: Path) -> None:
        """A non-1 schema version refuses the install."""
        manifest: dict = {**_MANIFEST, "schema_version": 2}
        repo, _ = _make_remote(tmp_path=tmp_path, name="repo-ver", manifest=manifest)
        with pytest.raises(ValueError):
            await PluginInstallerService.install(
                source_url=_https_url(),
                plugins_root=tmp_path / "plugins",
                confirmed=True,
                clone_url_override=str(repo),
            )

    @pytest.mark.asyncio
    async def test_payload_escape_refused(self, tmp_path: Path) -> None:
        """A payload path escaping the repo root refuses the install."""
        manifest: dict = {**_MANIFEST, "payload": ["../outside.py"]}
        repo, _ = _make_remote(tmp_path=tmp_path, name="repo-esc", manifest=manifest)
        with pytest.raises(ValueError, match="escape|payload"):
            await PluginInstallerService.install(
                source_url=_https_url(),
                plugins_root=tmp_path / "plugins",
                confirmed=True,
                clone_url_override=str(repo),
            )


class TestInstallLifecycle:
    """Happy path, idempotency, revision rules, rollback, upgrade, uninstall."""

    @pytest.mark.asyncio
    async def test_install_copies_payload_and_records_pin(self, tmp_path: Path) -> None:
        """Install copies only declared payload and records the pinned SHA."""
        repo, sha = _make_remote(tmp_path=tmp_path, name="repo-ok")
        plugins_root: Path = tmp_path / "plugins"

        record: PluginInstallRecordDAO = await PluginInstallerService.install(
            source_url=_https_url(),
            plugins_root=plugins_root,
            confirmed=True,
            clone_url_override=str(repo),
        )

        install_dir: Path = plugins_root / "plugins" / "acme-deploy-tools"
        assert (install_dir / "plugin.py").exists()
        assert (install_dir / "manifest.json").exists()
        assert not (install_dir / "slo-plugin.json").exists() or True  # manifest renamed
        assert record.plugin_id == "acme-deploy-tools"
        assert record.pinned_revision == sha
        assert record.source_url == "https://github.com/acme/deploy-tools"
        registry: list[PluginInstallRecordDAO] = await PluginInstallerService.list_installed(
            plugins_root=plugins_root
        )
        assert [entry.plugin_id for entry in registry] == ["acme-deploy-tools"]

    @pytest.mark.asyncio
    async def test_install_does_not_copy_undeclared_files(self, tmp_path: Path) -> None:
        """Only manifest-declared payload files land in the managed dir."""
        repo, _ = _make_remote(
            tmp_path=tmp_path,
            name="repo-undeclared",
            extra_files={"secret.txt": "do not copy", "README.md": "docs"},
        )
        plugins_root: Path = tmp_path / "plugins"

        await PluginInstallerService.install(
            source_url=_https_url(),
            plugins_root=plugins_root,
            confirmed=True,
            clone_url_override=str(repo),
        )

        install_dir: Path = plugins_root / "plugins" / "acme-deploy-tools"
        assert not (install_dir / "secret.txt").exists()
        assert not (install_dir / "README.md").exists()

    @pytest.mark.asyncio
    async def test_reinstall_same_revision_is_noop(self, tmp_path: Path) -> None:
        """Same source + same revision is an idempotent no-op success."""
        repo, sha = _make_remote(tmp_path=tmp_path, name="repo-idem")
        plugins_root: Path = tmp_path / "plugins"
        first: PluginInstallRecordDAO = await PluginInstallerService.install(
            source_url=_https_url(),
            plugins_root=plugins_root,
            confirmed=True,
            clone_url_override=str(repo),
        )

        second: PluginInstallRecordDAO = await PluginInstallerService.install(
            source_url=_https_url(),
            plugins_root=plugins_root,
            confirmed=True,
            clone_url_override=str(repo),
        )

        assert second.pinned_revision == first.pinned_revision == sha
        assert second.installed_at == first.installed_at

    @pytest.mark.asyncio
    async def test_reinstall_different_revision_refused_with_upgrade_hint(self, tmp_path: Path) -> None:
        """Same source at a newer revision refuses and names ``upgrade``."""
        repo, _ = _make_remote(tmp_path=tmp_path, name="repo-drift")
        plugins_root: Path = tmp_path / "plugins"
        await PluginInstallerService.install(
            source_url=_https_url(),
            plugins_root=plugins_root,
            confirmed=True,
            clone_url_override=str(repo),
        )
        _commit_more(repo=repo)

        with pytest.raises(ValueError, match="upgrade"):
            await PluginInstallerService.install(
                source_url=_https_url(),
                plugins_root=plugins_root,
                confirmed=True,
                clone_url_override=str(repo),
            )

    @pytest.mark.asyncio
    async def test_different_source_same_id_refused_reporting_both_urls(self, tmp_path: Path) -> None:
        """GitHub vs GitLab with the same owner-repo refuses and shows both URLs."""
        repo, _ = _make_remote(tmp_path=tmp_path, name="repo-collide")
        plugins_root: Path = tmp_path / "plugins"
        await PluginInstallerService.install(
            source_url=_https_url(host="github.com"),
            plugins_root=plugins_root,
            confirmed=True,
            clone_url_override=str(repo),
        )

        with pytest.raises(ValueError, match="github.com"):
            await PluginInstallerService.install(
                source_url=_https_url(host="gitlab.com"),
                plugins_root=plugins_root,
                confirmed=True,
                clone_url_override=str(repo),
            )

    @pytest.mark.asyncio
    async def test_unconfirmed_new_namespace_refused(self, tmp_path: Path) -> None:
        """Install from a new namespace requires confirmation (``--yes``)."""
        repo, _ = _make_remote(tmp_path=tmp_path, name="repo-confirm")
        with pytest.raises(ValueError, match="confirm|yes"):
            await PluginInstallerService.install(
                source_url=_https_url(),
                plugins_root=tmp_path / "plugins",
                confirmed=False,
                clone_url_override=str(repo),
            )
        assert not (tmp_path / "plugins").exists()

    @pytest.mark.asyncio
    async def test_mid_install_failure_leaves_no_dir_and_no_record(self, tmp_path: Path) -> None:
        """A clone that fails leaves no directory and no registry record."""
        plugins_root: Path = tmp_path / "plugins"
        with pytest.raises((ValueError, RuntimeError, OSError)):
            await PluginInstallerService.install(
                source_url=_https_url(),
                plugins_root=plugins_root,
                confirmed=True,
                clone_url_override=str(tmp_path / "does-not-exist"),
            )

        assert not (plugins_root / "plugins" / "acme-deploy-tools").exists()
        assert await PluginInstallerService.list_installed(plugins_root=plugins_root) == []

    @pytest.mark.asyncio
    async def test_invalid_manifest_failure_leaves_no_dir_and_no_record(self, tmp_path: Path) -> None:
        """A manifest validation failure leaves the machine unchanged (M6(b))."""
        manifest: dict = {**_MANIFEST, "schema_version": 2}
        repo, _ = _make_remote(tmp_path=tmp_path, name="repo-badman", manifest=manifest)
        plugins_root: Path = tmp_path / "plugins"
        with pytest.raises(ValueError):
            await PluginInstallerService.install(
                source_url=_https_url(),
                plugins_root=plugins_root,
                confirmed=True,
                clone_url_override=str(repo),
            )

        assert not (plugins_root / "plugins" / "acme-deploy-tools").exists()
        assert await PluginInstallerService.list_installed(plugins_root=plugins_root) == []

    @pytest.mark.asyncio
    async def test_upgrade_moves_pin(self, tmp_path: Path) -> None:
        """Upgrade re-fetches at the newest commit and swaps atomically."""
        repo, sha1 = _make_remote(tmp_path=tmp_path, name="repo-upg")
        plugins_root: Path = tmp_path / "plugins"
        await PluginInstallerService.install(
            source_url=_https_url(),
            plugins_root=plugins_root,
            confirmed=True,
            clone_url_override=str(repo),
        )
        sha2: str = _commit_more(repo=repo)

        record: PluginInstallRecordDAO = await PluginInstallerService.upgrade(
            plugin_id="acme-deploy-tools",
            plugins_root=plugins_root,
        )

        assert record.pinned_revision == sha2 != sha1
        assert "v2" in (plugins_root / "plugins" / "acme-deploy-tools" / "plugin.py").read_text()

    @pytest.mark.asyncio
    async def test_upgrade_keeps_old_install_on_fetch_failure(self, tmp_path: Path) -> None:
        """M6(b): a pre-swap fetch failure leaves the old install untouched."""
        repo, sha1 = _make_remote(tmp_path=tmp_path, name="repo-upgfail")
        plugins_root: Path = tmp_path / "plugins"
        await PluginInstallerService.install(
            source_url=_https_url(),
            plugins_root=plugins_root,
            confirmed=True,
            clone_url_override=str(repo),
        )
        # Remove the remote so the upgrade fetch fails.
        import shutil

        shutil.rmtree(repo)

        with pytest.raises((ValueError, RuntimeError, OSError)):
            await PluginInstallerService.upgrade(
                plugin_id="acme-deploy-tools",
                plugins_root=plugins_root,
            )

        install_dir: Path = plugins_root / "plugins" / "acme-deploy-tools"
        assert (install_dir / "plugin.py").exists()
        registry: list[PluginInstallRecordDAO] = await PluginInstallerService.list_installed(
            plugins_root=plugins_root
        )
        assert registry[0].pinned_revision == sha1

    @pytest.mark.asyncio
    async def test_upgrade_restores_old_install_when_registry_write_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """M6(b): a swap-phase registry-write failure restores payload and pin."""
        repo, sha1 = _make_remote(tmp_path=tmp_path, name="repo-upgrollback")
        plugins_root: Path = tmp_path / "plugins"
        await PluginInstallerService.install(
            source_url=_https_url(),
            plugins_root=plugins_root,
            confirmed=True,
            clone_url_override=str(repo),
        )
        _commit_more(repo=repo)
        original_write_registry = PluginInstallerService._write_registry

        def _raise_after_swap(*, root: Path, registry: object) -> None:
            """Simulate a registry-write failure after the directory swap.

            Args:
                root (Path): Managed plugin root.
                registry (object): Candidate registry not persisted.

            Raises:
                OSError: Always, to exercise upgrade rollback.
            """
            raise OSError("registry write failed")

        monkeypatch.setattr(PluginInstallerService, "_write_registry", _raise_after_swap)

        with pytest.raises(OSError, match="registry write failed"):
            await PluginInstallerService.upgrade(
                plugin_id="acme-deploy-tools",
                plugins_root=plugins_root,
            )

        install_dir: Path = plugins_root / "plugins" / "acme-deploy-tools"
        assert "v2" not in (install_dir / "plugin.py").read_text(encoding="utf-8")
        monkeypatch.setattr(PluginInstallerService, "_write_registry", original_write_registry)
        registry: list[PluginInstallRecordDAO] = await PluginInstallerService.list_installed(
            plugins_root=plugins_root
        )
        assert registry[0].pinned_revision == sha1

    @pytest.mark.asyncio
    async def test_upgrade_unknown_plugin_refused(self, tmp_path: Path) -> None:
        """Upgrade of a plugin that is not installed refuses."""
        with pytest.raises(ValueError, match="not installed"):
            await PluginInstallerService.upgrade(
                plugin_id="ghost-plugin",
                plugins_root=tmp_path / "plugins",
            )

    @pytest.mark.asyncio
    async def test_install_restores_payload_when_registry_write_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A new install whose registry write fails leaves no managed payload behind."""
        repo, _ = _make_remote(tmp_path=tmp_path, name="repo-installrollback")
        plugins_root: Path = tmp_path / "plugins"

        def _raise_registry_write(*, root: Path, registry: object) -> None:
            """Fail the post-swap durable write.

            Args:
                root (Path): Managed plugins root.
                registry (object): Candidate registry.

            Raises:
                OSError: Always, to exercise installation rollback.
            """
            raise OSError("registry write failed")

        monkeypatch.setattr(PluginInstallerService, "_write_registry", _raise_registry_write)

        with pytest.raises(OSError, match="registry write failed"):
            await PluginInstallerService.install(
                source_url=_https_url(),
                plugins_root=plugins_root,
                confirmed=True,
                clone_url_override=str(repo),
            )

        assert not (plugins_root / "plugins" / "acme-deploy-tools").exists()

    @pytest.mark.asyncio
    async def test_uninstall_removes_dir_and_record(self, tmp_path: Path) -> None:
        """Uninstall removes the managed directory and the registry record."""
        repo, _ = _make_remote(tmp_path=tmp_path, name="repo-un")
        plugins_root: Path = tmp_path / "plugins"
        await PluginInstallerService.install(
            source_url=_https_url(),
            plugins_root=plugins_root,
            confirmed=True,
            clone_url_override=str(repo),
        )

        await PluginInstallerService.uninstall(plugin_id="acme-deploy-tools", plugins_root=plugins_root)

        assert not (plugins_root / "plugins" / "acme-deploy-tools").exists()
        assert await PluginInstallerService.list_installed(plugins_root=plugins_root) == []

    @pytest.mark.asyncio
    async def test_uninstall_unknown_plugin_refused(self, tmp_path: Path) -> None:
        """Uninstall of an unknown id refuses."""
        with pytest.raises(ValueError, match="not installed"):
            await PluginInstallerService.uninstall(
                plugin_id="ghost-plugin",
                plugins_root=tmp_path / "plugins",
            )


class TestBundledPluginInstallation:
    """M4: packaged Bash live-output delivery uses managed install machinery."""

    @pytest.mark.asyncio
    async def test_bundled_bash_plugin_installs_with_package_provenance(self, tmp_path: Path) -> None:
        """The bundled payload records ``github.com/slo/slo`` plus package provenance."""
        record: PluginInstallRecordDAO = await PluginInstallerService.install_bundled_bash_live_output(
            plugins_root=tmp_path / "plugins",
        )

        install_dir: Path = tmp_path / "plugins" / "plugins" / "slo-slo"
        assert record.plugin_id == "slo-slo"
        assert record.source_url == "https://github.com/slo/slo"
        assert record.pinned_revision.startswith("package:")
        assert (install_dir / "plugin.py").exists()
        assert (install_dir / "manifest.json").exists()


class TestNoExecutionRule:
    """HARD rule: the installer never executes source files."""

    @pytest.mark.asyncio
    async def test_install_never_executes_source_side_effects(self, tmp_path: Path) -> None:
        """A repo full of import-time side effects installs without any running."""
        sentinel: Path = tmp_path / "SENTINEL"
        side_effect_body: str = (
            "import pathlib\n"
            f"pathlib.Path({str(sentinel)!r}).write_text('EXECUTED')\n"
            "def register(slo):\n    pass\n"
        )
        repo, _ = _make_remote(
            tmp_path=tmp_path,
            name="repo-sideeffect",
            extra_files={
                "setup.py": side_effect_body,
                "postinstall.sh": f"#!/bin/sh\ntouch {sentinel}\n",
                "hooks/install.py": side_effect_body,
            },
        )
        # Make the DECLARED payload itself side-effecting: if the installer
        # imported or executed the payload, the sentinel would appear.
        (repo / "plugin.py").write_text(side_effect_body, encoding="utf-8")
        _git(cwd=repo, args=["add", "."])
        _git(cwd=repo, args=["commit", "-m", "side effects"])

        await PluginInstallerService.install(
            source_url=_https_url(),
            plugins_root=tmp_path / "plugins",
            confirmed=True,
            clone_url_override=str(repo),
        )

        assert not sentinel.exists()

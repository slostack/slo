"""Tests for fail-closed project trust decisions."""

from __future__ import annotations

from pathlib import Path

from src.agents.slo_agent.plugins.trust import PluginTrustStore


class TestPluginTrustStore:
    """Project-local plugin execution requires an explicit durable decision."""

    def test_is_trusted_is_false_when_store_is_absent(self, tmp_path: Path) -> None:
        """Absent trust evidence fails closed for a project plugin directory."""
        store: PluginTrustStore = PluginTrustStore(store_path=tmp_path / "trust.json")

        assert store.is_trusted(project_dir=tmp_path / "project") is False

    def test_trust_persists_resolved_project_once(self, tmp_path: Path) -> None:
        """Trust records the canonical project path atomically and idempotently."""
        store_path: Path = tmp_path / "trust.json"
        project_dir: Path = tmp_path / "project"
        project_dir.mkdir()
        store: PluginTrustStore = PluginTrustStore(store_path=store_path)

        store.trust(project_dir=project_dir)
        store.trust(project_dir=project_dir)

        assert store.is_trusted(project_dir=project_dir) is True
        assert store_path.read_text(encoding="utf-8").count(str(project_dir.resolve())) == 1

    def test_is_trusted_is_false_when_store_is_corrupt(self, tmp_path: Path) -> None:
        """Malformed durable data cannot implicitly authorize arbitrary project code."""
        store_path: Path = tmp_path / "trust.json"
        store_path.write_text("not json", encoding="utf-8")
        store: PluginTrustStore = PluginTrustStore(store_path=store_path)

        assert store.is_trusted(project_dir=tmp_path) is False

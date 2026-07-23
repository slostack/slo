"""Tests for ``config.cfg`` (sub-spec 01.n §5.4 — ``_resolve_skills_dir``, spec 29 — user dirs)."""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

from config.cfg import _resolve_skills_dir


class TestResolveSkillsDir:
    """01.n §5.4: precedence — env > ~/.slo/skills > repo-local."""

    def test_env_override_wins(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        override = tmp_path / "explicit-skills"
        override.mkdir()
        monkeypatch.setenv("SLO_SKILLS_DIR", str(override))
        result = _resolve_skills_dir()
        assert result == str(override.resolve())
        assert os.path.isabs(result)

    def test_env_override_returns_absolute_even_when_dir_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Override is honoured verbatim — directory existence is the caller's problem."""
        nonexistent = tmp_path / "nope"
        monkeypatch.setenv("SLO_SKILLS_DIR", str(nonexistent))
        result = _resolve_skills_dir()
        assert result == str(nonexistent.resolve())
        assert os.path.isabs(result)

    def test_installed_path_when_env_unset_and_dir_exists(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("SLO_SKILLS_DIR", raising=False)
        fake_home = tmp_path / "home"
        (fake_home / ".slo" / "skills").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        result = _resolve_skills_dir()
        assert result == str(fake_home / ".slo" / "skills")

    def test_repo_local_fallback_when_install_dir_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("SLO_SKILLS_DIR", raising=False)
        fake_home = tmp_path / "home-without-slo"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        result = _resolve_skills_dir()
        # The repo-local fallback derives from cfg.py's parent.parent / "skills".
        # We don't pin the exact absolute path (depends on the test machine);
        # we assert it's absolute and ends with /skills.
        assert os.path.isabs(result)
        assert result.endswith(os.sep + "skills")


class TestHeadlessTimeoutDefaults:
    """Shipped timeout defaults exposed through ``config.cfg``."""

    def test_stream_inactivity_timeout_defaults_to_4800_seconds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Main-stream inactivity timeout ships with the 4800-second default."""
        monkeypatch.delenv("SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS", raising=False)
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.STREAM_INACTIVITY_TIMEOUT_SECONDS == 4800.0
        assert cfg_module.cfg("SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS") == "4800.0"

    def test_subagent_inactivity_timeout_defaults_to_3600_seconds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Child-process inactivity timeout ships with the 3600-second default."""
        monkeypatch.delenv("SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("SLO_SUBAGENT_INACTIVITY_TIMEOUT", raising=False)
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.SUBAGENT_INACTIVITY_TIMEOUT_SECONDS == 3600.0
        assert cfg_module.cfg("SUBAGENT_INACTIVITY_TIMEOUT_SECONDS") == "3600.0"


class TestDetachedWorkflowConfig:
    """Detached-workflow kill switch and cap defaults."""

    def test_detached_workflows_default_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Detached workflows ship enabled by default."""
        monkeypatch.delenv("SLO_DETACHED_WORKFLOWS", raising=False)
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.DETACHED_WORKFLOWS is True
        assert cfg_module.cfg("DETACHED_WORKFLOWS") == "1"

    def test_detached_workflows_false_strings_disable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """False-like env values disable detached workflows."""
        monkeypatch.setenv("SLO_DETACHED_WORKFLOWS", "0")
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.DETACHED_WORKFLOWS is False
        assert cfg_module.cfg("DETACHED_WORKFLOWS") == "0"

    def test_max_detached_workflows_defaults_to_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Detached workflow cap defaults to two live workflows."""
        monkeypatch.delenv("SLO_MAX_DETACHED_WORKFLOWS", raising=False)
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.MAX_DETACHED_WORKFLOWS == 2
        assert cfg_module.cfg("MAX_DETACHED_WORKFLOWS") == "2"

    def test_invalid_max_detached_workflows_falls_back_to_two(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Non-integer detached workflow caps fall back to the shipped default."""
        monkeypatch.setenv("SLO_MAX_DETACHED_WORKFLOWS", "not-an-int")
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.MAX_DETACHED_WORKFLOWS == 2


class TestUserSkillsDirConstants:
    """Spec 29: USER_SKILLS_DIR and USER_WORKFLOWS_DIR config constants."""

    def test_user_skills_dir_defaults_to_slo_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """USER_SKILLS_DIR ends with 'user_skills' under SLO_HOME by default."""
        monkeypatch.delenv("SLO_USER_SKILLS_DIR", raising=False)
        monkeypatch.setenv("SLO_HOME", str(tmp_path))
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.USER_SKILLS_DIR == str(tmp_path / "user_skills")

    def test_user_workflows_dir_defaults_to_slo_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """USER_WORKFLOWS_DIR ends with 'user_workflows' under SLO_HOME by default."""
        monkeypatch.delenv("SLO_USER_WORKFLOWS_DIR", raising=False)
        monkeypatch.setenv("SLO_HOME", str(tmp_path))
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.USER_WORKFLOWS_DIR == str(tmp_path / "user_workflows")

    def test_user_skills_dir_env_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """SLO_USER_SKILLS_DIR env var overrides the default."""
        custom = str(tmp_path / "custom_skills")
        monkeypatch.setenv("SLO_USER_SKILLS_DIR", custom)
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.USER_SKILLS_DIR == custom

    def test_user_workflows_dir_env_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """SLO_USER_WORKFLOWS_DIR env var overrides the default."""
        custom = str(tmp_path / "custom_workflows")
        monkeypatch.setenv("SLO_USER_WORKFLOWS_DIR", custom)
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.USER_WORKFLOWS_DIR == custom

    def test_user_skills_dir_in_cfg_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """USER_SKILLS_DIR is accessible via cfg('USER_SKILLS_DIR')."""
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        result = cfg_module.cfg("USER_SKILLS_DIR")
        assert result is not None
        assert "user_skills" in result

    def test_user_workflows_dir_in_cfg_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """USER_WORKFLOWS_DIR is accessible via cfg('USER_WORKFLOWS_DIR')."""
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        result = cfg_module.cfg("USER_WORKFLOWS_DIR")
        assert result is not None
        assert "user_workflows" in result

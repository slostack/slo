"""Tests for ``config.cfg`` (sub-spec 01.n §5.4 — ``_resolve_skills_dir``, spec 29 — user dirs,
knowledge-base resolution)."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

import config.cfg as cfg_module


def _fields(location: object) -> tuple[str, str]:
    """Return ``(path, source)``; other test modules reload ``config.cfg``, so
    ``ResolvedDirectory`` instances from different loads never compare equal."""
    return (location.path, location.source)  # type: ignore[attr-defined]


def _resolve_skills_dir() -> str:
    return cfg_module._resolve_skills_dir()


def _resolve_skills_location() -> object:
    return cfg_module._resolve_skills_location()


def _resolve_kb_location() -> object:
    return cfg_module._resolve_kb_location()


class TestResolveSkillsDir:
    """01.n §5.4: precedence — env > ~/.slo/skills > repo-local."""

    def test_env_override_wins(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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

    def test_installed_path_when_env_unset_and_tree_is_populated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("SLO_SKILLS_DIR", raising=False)
        monkeypatch.delenv("SLO_HOME", raising=False)
        fake_home = tmp_path / "home"
        installed = fake_home / ".slo" / "skills"
        installed.mkdir(parents=True)
        (installed / "INDEX.md").write_text("# index")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        result = _resolve_skills_dir()
        assert result == str(installed)

    def test_empty_installed_dir_does_not_shadow_packaged_tree(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A stale ``~/.slo/skills`` with no INDEX.md must fall through.

        Regression guard: an empty leftover directory previously won the
        precedence race and left the agent with zero vendored skills.
        """
        monkeypatch.delenv("SLO_SKILLS_DIR", raising=False)
        monkeypatch.delenv("SLO_HOME", raising=False)
        fake_home = tmp_path / "home"
        (fake_home / ".slo" / "skills").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        result = _resolve_skills_dir()
        assert result != str(fake_home / ".slo" / "skills")
        assert result.endswith(os.sep + "skills")

    def test_packaged_fallback_when_install_dir_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("SLO_SKILLS_DIR", raising=False)
        monkeypatch.delenv("SLO_HOME", raising=False)
        fake_home = tmp_path / "home-without-slo"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        result = _resolve_skills_dir()
        # The packaged fallback derives from cfg.py's parent.parent / "skills":
        # site-packages/ for a pipx install, the repo root for a dev clone.
        # We don't pin the exact absolute path (depends on the test machine);
        # we assert it's absolute and ends with /skills.
        assert os.path.isabs(result)
        assert result.endswith(os.sep + "skills")

    def test_packaged_fallback_is_derived_from_cfg_module_location(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The fallback is ``<parent of config/>/skills``, wherever cfg.py lives.

        That parent is ``site-packages/`` for a pipx install and the repo root
        for a dev clone — the invariant that makes a shipped ``skills/``
        directory discoverable. Driven off a synthetic layout so the assertion
        does not depend on how this checkout happens to be installed.
        """
        import config.cfg as cfg_module

        monkeypatch.delenv("SLO_SKILLS_DIR", raising=False)
        monkeypatch.delenv("SLO_HOME", raising=False)
        fake_home = tmp_path / "home-without-slo"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        fake_install_root = tmp_path / "site-packages"
        (fake_install_root / "config").mkdir(parents=True)
        (fake_install_root / "skills").mkdir()
        monkeypatch.setattr(cfg_module, "__file__", str(fake_install_root / "config" / "cfg.py"))

        result = _resolve_skills_dir()
        assert result == str(fake_install_root / "skills")


class TestResolveSkillsLocation:
    """The skills directory honours ``SLO_HOME`` and names the setting that supplied it."""

    def test_source_is_slo_skills_dir_when_env_is_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_SKILLS_DIR", str(tmp_path / "explicit"))
        assert _fields(_resolve_skills_location()) == (str(tmp_path / "explicit"), "`SLO_SKILLS_DIR`")

    def test_empty_slo_skills_dir_is_treated_as_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_SKILLS_DIR", "")
        monkeypatch.setenv("SLO_HOME", str(tmp_path / "empty-home"))
        assert _fields(_resolve_skills_location())[1] == "the installed slo package"

    def test_populated_tree_under_slo_home_wins_over_package(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``$SLO_HOME/skills`` is the second candidate, not a hard-coded ``~/.slo/skills``."""
        monkeypatch.delenv("SLO_SKILLS_DIR", raising=False)
        slo_home = tmp_path / "custom slo home"
        (slo_home / "skills").mkdir(parents=True)
        (slo_home / "skills" / "INDEX.md").write_text("# index")
        monkeypatch.setenv("SLO_HOME", str(slo_home))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "unrelated-home"))
        assert _fields(_resolve_skills_location()) == (str(slo_home / "skills"), "`$SLO_HOME/skills`")

    def test_home_dot_slo_is_ignored_when_slo_home_points_elsewhere(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("SLO_SKILLS_DIR", raising=False)
        fake_home = tmp_path / "home"
        (fake_home / ".slo" / "skills").mkdir(parents=True)
        (fake_home / ".slo" / "skills" / "INDEX.md").write_text("# index")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        monkeypatch.setenv("SLO_HOME", str(tmp_path / "elsewhere"))
        assert _fields(_resolve_skills_location())[1] == "the installed slo package"

    def test_resolve_skills_dir_returns_the_location_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_SKILLS_DIR", str(tmp_path / "explicit"))
        assert _resolve_skills_dir() == _fields(_resolve_skills_location())[0]


class TestResolveKbLocation:
    """KB lookup: ``SLO_KB_DIR`` → ``KB_DIR`` → ``$SLO_HOME/KnowledgeBase/KB``."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        for name in ("SLO_KB_DIR", "KB_DIR", "SLO_HOME"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    def test_default_is_under_home_dot_slo_when_nothing_is_set(self, tmp_path: Path) -> None:
        assert _fields(_resolve_kb_location()) == (
            str(tmp_path / "home" / ".slo" / "KnowledgeBase" / "KB"),
            "the default `$SLO_HOME/KnowledgeBase/KB`",
        )

    def test_default_follows_slo_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SLO_HOME", str(tmp_path / "slo home"))
        assert _fields(_resolve_kb_location())[0] == str(tmp_path / "slo home" / "KnowledgeBase" / "KB")

    def test_kb_dir_is_a_fallback_alias(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("KB_DIR", str(tmp_path / "alias"))
        assert _fields(_resolve_kb_location()) == (str(tmp_path / "alias"), "`KB_DIR`")

    def test_slo_kb_dir_wins_over_kb_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SLO_KB_DIR", str(tmp_path / "canonical"))
        monkeypatch.setenv("KB_DIR", str(tmp_path / "alias"))
        assert _fields(_resolve_kb_location()) == (str(tmp_path / "canonical"), "`SLO_KB_DIR`")

    def test_empty_values_are_treated_as_unset(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SLO_KB_DIR", "")
        monkeypatch.setenv("KB_DIR", "")
        assert _fields(_resolve_kb_location())[1] == "the default `$SLO_HOME/KnowledgeBase/KB`"

    def test_a_path_to_a_file_resolves_to_its_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``SLO_KB_DIR=.../KB/Welcome.md`` is a common misconfiguration; use ``.../KB``."""
        kb = tmp_path / "KB"
        kb.mkdir()
        (kb / "Welcome.md").write_text("# Welcome")
        monkeypatch.setenv("SLO_KB_DIR", str(kb / "Welcome.md"))
        assert _fields(_resolve_kb_location())[0] == str(kb)

    def test_relative_and_tilde_values_become_absolute(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("SLO_KB_DIR", "~/notes/KB")
        assert _fields(_resolve_kb_location())[0] == str(tmp_path / "home" / "notes" / "KB")

    def test_resolution_never_creates_the_directory(self, tmp_path: Path) -> None:
        assert not Path(_fields(_resolve_kb_location())[0]).exists()

    def test_module_constants_expose_the_resolved_location(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("KB_DIR", str(tmp_path / "alias"))
        importlib.reload(cfg_module)
        assert (cfg_module.KB_LOCATION.path, cfg_module.KB_LOCATION.source) == (
            str(tmp_path / "alias"),
            "`KB_DIR`",
        )
        assert cfg_module.SLO_KB_DIR == str(tmp_path / "alias")
        assert cfg_module.cfg("SLO_KB_DIR") == str(tmp_path / "alias")


class TestHeadlessTimeoutDefaults:
    """Shipped timeout defaults exposed through ``config.cfg``."""

    def test_stream_inactivity_timeout_defaults_to_10800_seconds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Main-stream inactivity timeout ships with the 10800-second default."""
        monkeypatch.delenv("SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS", raising=False)
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.STREAM_INACTIVITY_TIMEOUT_SECONDS == 10800.0
        assert cfg_module.cfg("SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS") == "10800.0"

    def test_subagent_inactivity_timeout_defaults_to_7200_seconds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Child-process inactivity timeout ships with the 7200-second default."""
        monkeypatch.delenv("SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("SLO_SUBAGENT_INACTIVITY_TIMEOUT", raising=False)
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.SUBAGENT_INACTIVITY_TIMEOUT_SECONDS == 7200.0
        assert cfg_module.cfg("SUBAGENT_INACTIVITY_TIMEOUT_SECONDS") == "7200.0"


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

    def test_user_skills_dir_defaults_to_slo_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """USER_SKILLS_DIR ends with 'user_skills' under SLO_HOME by default."""
        monkeypatch.delenv("SLO_USER_SKILLS_DIR", raising=False)
        monkeypatch.setenv("SLO_HOME", str(tmp_path))
        import config.cfg as cfg_module

        importlib.reload(cfg_module)
        assert cfg_module.USER_SKILLS_DIR == str(tmp_path / "user_skills")

    def test_user_workflows_dir_defaults_to_slo_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
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

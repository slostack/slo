"""Tests for ``SkillsLoader`` and ``SkillEntryDAO`` (sub-spec 18.02, spec 29).

Covers:
- Happy-path loading from the real skills directory.
- Empty-list return when skills_dir does not exist.
- Skipping entries with no description.
- Skipping entries with ``disable-model-invocation: true``.
- Graceful handling of malformed YAML frontmatter.
- Graceful handling of missing frontmatter block.
- Graceful handling of non-dict YAML top-level value.
- Graceful handling of an unreadable file.
- load_merged: all vendored returned when user dirs absent.
- load_merged: user skill with unique name is appended.
- load_merged: user workflow with unique name is appended.
- load_merged: user skill overrides vendored by name.
- load_merged: user workflow overrides vendored by name.
- load_merged: override log event is emitted.
- load_merged: both user_skills and user_workflows can each override different vendored entries.
- load_merged: absence of user dirs is not an error.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Optional

import pytest

from config.cfg import SKILLS_DIR
from src.agents.slo_agent.skills.dao import SkillEntryDAO
from src.agents.slo_agent.skills.service import SkillsLoader


class TestSkillsLoaderHappyPath:
    """SkillsLoader correctly discovers and parses real SKILL.md files."""

    def test_loads_skills_from_real_skills_dir(self) -> None:
        """SkillsLoader returns a non-empty list when pointed at the real skills dir."""
        skills: list[SkillEntryDAO] = SkillsLoader.load(skills_dir=SKILLS_DIR)
        assert len(skills) > 0

    def test_loaded_skills_have_non_empty_names_and_descriptions(self) -> None:
        """Every returned entry has a non-empty name and description."""
        skills: list[SkillEntryDAO] = SkillsLoader.load(skills_dir=SKILLS_DIR)
        for skill in skills:
            assert skill.name.strip(), f"Empty name for skill at {skill.file_path}"
            assert skill.description.strip(), f"Empty description for skill at {skill.file_path}"

    def test_loaded_skills_have_absolute_file_paths(self) -> None:
        """Every returned entry carries an absolute path to its SKILL.md."""
        skills: list[SkillEntryDAO] = SkillsLoader.load(skills_dir=SKILLS_DIR)
        for skill in skills:
            assert os.path.isabs(skill.file_path), f"Non-absolute path: {skill.file_path}"

    def test_loaded_skills_disable_model_invocation_is_false(self) -> None:
        """All returned skills have disable_model_invocation=False (eligible for XML)."""
        skills: list[SkillEntryDAO] = SkillsLoader.load(skills_dir=SKILLS_DIR)
        for skill in skills:
            assert skill.disable_model_invocation is False


class TestSkillsLoaderMissingDir:
    """SkillsLoader returns empty list when skills_dir does not exist."""

    def test_returns_empty_list_for_missing_dir(self) -> None:
        """A non-existent directory produces an empty list, no exception."""
        skills: list[SkillEntryDAO] = SkillsLoader.load(
            skills_dir="/does/not/exist/at/all/12345",
        )
        assert skills == []


class TestSkillsLoaderFiltering:
    """SkillsLoader filters out skills that should not be shown to the model."""

    def test_skips_skill_with_no_description(self, tmp_path: Path) -> None:
        """A SKILL.md with frontmatter but no description field is silently skipped."""
        skill_dir: Path = tmp_path / "no-desc-skill"
        skill_dir.mkdir(parents=True)
        skill_file: Path = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: no-description-skill\n---\n\n# Body",
            encoding="utf-8",
        )
        skills: list[SkillEntryDAO] = SkillsLoader.load(skills_dir=str(tmp_path))
        names: list[str] = [s.name for s in skills]
        assert "no-description-skill" not in names
        assert len(skills) == 0

    def test_skips_disable_model_invocation_true(self, tmp_path: Path) -> None:
        """A skill with ``disable-model-invocation: true`` is excluded from results."""
        skill_dir: Path = tmp_path / "slash-only-skill"
        skill_dir.mkdir(parents=True)
        skill_file: Path = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: slash-only\ndescription: Only via /slash.\ndisable-model-invocation: true\n---\n\n# Body",
            encoding="utf-8",
        )
        skills: list[SkillEntryDAO] = SkillsLoader.load(skills_dir=str(tmp_path))
        names: list[str] = [s.name for s in skills]
        assert "slash-only" not in names
        assert len(skills) == 0

    def test_includes_skill_without_disable_flag(self, tmp_path: Path) -> None:
        """A skill without ``disable-model-invocation`` is included."""
        skill_dir: Path = tmp_path / "normal-skill"
        skill_dir.mkdir(parents=True)
        skill_file: Path = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: normal-skill\ndescription: Does normal things.\n---\n\n# Body",
            encoding="utf-8",
        )
        skills: list[SkillEntryDAO] = SkillsLoader.load(skills_dir=str(tmp_path))
        assert len(skills) == 1
        assert skills[0].name == "normal-skill"
        assert skills[0].description == "Does normal things."


class TestSkillsLoaderFallbacks:
    """SkillsLoader handles edge cases gracefully without raising."""

    def test_falls_back_gracefully_on_malformed_yaml(self, tmp_path: Path) -> None:
        """A SKILL.md with invalid YAML frontmatter is silently skipped."""
        skill_dir: Path = tmp_path / "bad-yaml-skill"
        skill_dir.mkdir(parents=True)
        skill_file: Path = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: [unclosed bracket\ndescription: broken\n---\n\n# Body",
            encoding="utf-8",
        )
        # Must not raise; malformed file is skipped
        skills: list[SkillEntryDAO] = SkillsLoader.load(skills_dir=str(tmp_path))
        assert len(skills) == 0

    def test_falls_back_gracefully_on_no_frontmatter(self, tmp_path: Path) -> None:
        """A SKILL.md with no --- block returns an empty-dict frontmatter and is skipped."""
        skill_dir: Path = tmp_path / "no-frontmatter-skill"
        skill_dir.mkdir(parents=True)
        skill_file: Path = skill_dir / "SKILL.md"
        skill_file.write_text(
            "# Just a heading\n\nNo frontmatter here.",
            encoding="utf-8",
        )
        skills: list[SkillEntryDAO] = SkillsLoader.load(skills_dir=str(tmp_path))
        assert len(skills) == 0

    def test_falls_back_gracefully_on_non_dict_yaml(self, tmp_path: Path) -> None:
        """YAML that parses to a non-dict (e.g. a list) is treated as empty frontmatter."""
        skill_dir: Path = tmp_path / "list-yaml-skill"
        skill_dir.mkdir(parents=True)
        skill_file: Path = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\n- item1\n- item2\n---\n\n# Body",
            encoding="utf-8",
        )
        skills: list[SkillEntryDAO] = SkillsLoader.load(skills_dir=str(tmp_path))
        assert len(skills) == 0

    def test_falls_back_on_name_to_parent_dir_name(self, tmp_path: Path) -> None:
        """When frontmatter has no ``name`` key the parent directory name is used."""
        skill_dir: Path = tmp_path / "my-unnamed-skill"
        skill_dir.mkdir(parents=True)
        skill_file: Path = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\ndescription: Does a thing without a name.\n---\n\n# Body",
            encoding="utf-8",
        )
        skills: list[SkillEntryDAO] = SkillsLoader.load(skills_dir=str(tmp_path))
        assert len(skills) == 1
        assert skills[0].name == "my-unnamed-skill"


# ---------------------------------------------------------------------------
# Helpers shared by load_merged tests
# ---------------------------------------------------------------------------


def _write_skill(
    directory: Path,
    slug: str,
    name: str,
    description: str = "A test skill",
) -> Path:
    """Write a minimal SKILL.md under ``directory/<slug>/SKILL.md``.

    Args:
        directory (Path): Root directory in which to create the slug sub-folder.
        slug (str): Sub-folder name (also used as fallback name when frontmatter
            omits ``name``).
        name (str): The ``name`` frontmatter field for the skill.
        description (str): One-line description. Defaults to "A test skill".

    Returns:
        Path: Absolute path to the written SKILL.md file.
    """
    skill_dir: Path = directory / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    content: str = (
        f"---\nname: {name}\ndescription: {description}\n"
        f"when_to_use: Use for testing.\ngroup: test\nkind: skill\n---\n\n# {name}\n"
    )
    skill_file: Path = skill_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


class TestSkillsLoaderLoadMerged:
    """SkillsLoader.load_merged merges vendored + user_skills + user_workflows."""

    def test_returns_all_vendored_when_user_dirs_empty(self, tmp_path: Path) -> None:
        """All vendored skills appear when user dirs do not exist."""
        vendored_dir: Path = tmp_path / "vendored"
        _write_skill(directory=vendored_dir, slug="skill-a", name="skill-a")
        _write_skill(directory=vendored_dir, slug="skill-b", name="skill-b")

        result: list[SkillEntryDAO] = SkillsLoader.load_merged(
            vendored_skills_dir=str(vendored_dir),
            user_skills_dir=str(tmp_path / "absent_user"),
            user_workflows_dir=str(tmp_path / "absent_workflows"),
        )

        names: list[str] = [e.name for e in result]
        assert "skill-a" in names
        assert "skill-b" in names
        assert len(result) == 2

    def test_appends_user_skills_with_unique_name(self, tmp_path: Path) -> None:
        """User skill with a unique name is appended to the merged result."""
        vendored_dir: Path = tmp_path / "vendored"
        user_dir: Path = tmp_path / "user_skills"
        _write_skill(directory=vendored_dir, slug="vendored-skill", name="vendored-skill")
        _write_skill(directory=user_dir, slug="my-custom", name="my-custom")

        result: list[SkillEntryDAO] = SkillsLoader.load_merged(
            vendored_skills_dir=str(vendored_dir),
            user_skills_dir=str(user_dir),
            user_workflows_dir=str(tmp_path / "absent"),
        )

        names: list[str] = [e.name for e in result]
        assert "vendored-skill" in names
        assert "my-custom" in names
        assert len(result) == 2

    def test_appends_user_workflows_with_unique_name(self, tmp_path: Path) -> None:
        """User workflow with a unique name is appended to the merged result."""
        vendored_dir: Path = tmp_path / "vendored"
        workflows_dir: Path = tmp_path / "user_workflows"
        _write_skill(directory=vendored_dir, slug="vendored-skill", name="vendored-skill")
        _write_skill(directory=workflows_dir, slug="my-workflow", name="my-workflow")

        result: list[SkillEntryDAO] = SkillsLoader.load_merged(
            vendored_skills_dir=str(vendored_dir),
            user_skills_dir=str(tmp_path / "absent"),
            user_workflows_dir=str(workflows_dir),
        )

        names: list[str] = [e.name for e in result]
        assert "my-workflow" in names
        assert len(result) == 2

    def test_user_skill_overrides_vendored_by_name(self, tmp_path: Path) -> None:
        """User skill with same name as vendored replaces it; only one entry in result."""
        vendored_dir: Path = tmp_path / "vendored"
        user_dir: Path = tmp_path / "user_skills"
        _write_skill(
            directory=vendored_dir,
            slug="build-routers",
            name="build-routers",
            description="Vendored version",
        )
        _write_skill(
            directory=user_dir,
            slug="build-routers",
            name="build-routers",
            description="User override version",
        )

        result: list[SkillEntryDAO] = SkillsLoader.load_merged(
            vendored_skills_dir=str(vendored_dir),
            user_skills_dir=str(user_dir),
            user_workflows_dir=str(tmp_path / "absent"),
        )

        assert len(result) == 1
        entry: SkillEntryDAO = result[0]
        assert entry.name == "build-routers"
        assert "user_skills" in entry.file_path  # user path wins

    def test_user_workflow_overrides_vendored_by_name(self, tmp_path: Path) -> None:
        """User workflow with same name overrides the vendored skill with that name."""
        vendored_dir: Path = tmp_path / "vendored"
        workflows_dir: Path = tmp_path / "user_workflows"
        _write_skill(
            directory=vendored_dir,
            slug="specification-development",
            name="specification-development",
        )
        _write_skill(
            directory=workflows_dir,
            slug="specification-development",
            name="specification-development",
            description="My custom workflow",
        )

        result: list[SkillEntryDAO] = SkillsLoader.load_merged(
            vendored_skills_dir=str(vendored_dir),
            user_skills_dir=str(tmp_path / "absent"),
            user_workflows_dir=str(workflows_dir),
        )

        assert len(result) == 1
        assert "user_workflows" in result[0].file_path

    def test_populated_vendored_tree_does_not_short_circuit_user_dirs(self, tmp_path: Path) -> None:
        """Finding vendored skills must not stop the user trees from loading.

        Regression guard: the three trees are additive, never first-match-wins.
        A populated vendored tree and populated user trees all contribute.
        """
        vendored_dir: Path = tmp_path / "vendored"
        user_dir: Path = tmp_path / "user_skills"
        workflows_dir: Path = tmp_path / "user_workflows"
        _write_skill(directory=vendored_dir, slug="vendored-one", name="vendored-one")
        _write_skill(directory=vendored_dir, slug="vendored-two", name="vendored-two")
        _write_skill(directory=user_dir, slug="user-one", name="user-one")
        _write_skill(directory=workflows_dir, slug="workflow-one", name="workflow-one")

        result: list[SkillEntryDAO] = SkillsLoader.load_merged(
            vendored_skills_dir=str(vendored_dir),
            user_skills_dir=str(user_dir),
            user_workflows_dir=str(workflows_dir),
        )

        names: set[str] = {entry.name for entry in result}
        assert names == {"vendored-one", "vendored-two", "user-one", "workflow-one"}

    def test_user_dirs_still_load_when_vendored_tree_is_missing(self, tmp_path: Path) -> None:
        """The inverse: an absent vendored tree must not suppress user skills."""
        user_dir: Path = tmp_path / "user_skills"
        workflows_dir: Path = tmp_path / "user_workflows"
        _write_skill(directory=user_dir, slug="user-one", name="user-one")
        _write_skill(directory=workflows_dir, slug="workflow-one", name="workflow-one")

        result: list[SkillEntryDAO] = SkillsLoader.load_merged(
            vendored_skills_dir=str(tmp_path / "absent_vendored"),
            user_skills_dir=str(user_dir),
            user_workflows_dir=str(workflows_dir),
        )

        names: set[str] = {entry.name for entry in result}
        assert names == {"user-one", "workflow-one"}

    def test_logs_error_when_vendored_tree_yields_nothing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An empty vendored tree is logged at ERROR, not silently tolerated.

        This is the signal that distinguishes a broken install from the model
        simply choosing not to use a skill.
        """
        import logging

        user_dir: Path = tmp_path / "user_skills"
        _write_skill(directory=user_dir, slug="user-one", name="user-one")
        missing_vendored: Path = tmp_path / "absent_vendored"

        with caplog.at_level(logging.ERROR):
            SkillsLoader.load_merged(
                vendored_skills_dir=str(missing_vendored),
                user_skills_dir=str(user_dir),
                user_workflows_dir=str(tmp_path / "absent_workflows"),
            )

        assert any("no vendored skills found" in record.getMessage() for record in caplog.records)

    def test_logs_no_error_when_vendored_tree_is_populated(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The healthy path stays quiet so the error above keeps its meaning."""
        import logging

        vendored_dir: Path = tmp_path / "vendored"
        _write_skill(directory=vendored_dir, slug="vendored-one", name="vendored-one")

        with caplog.at_level(logging.ERROR):
            SkillsLoader.load_merged(
                vendored_skills_dir=str(vendored_dir),
                user_skills_dir=str(tmp_path / "absent_user"),
                user_workflows_dir=str(tmp_path / "absent_workflows"),
            )

        assert not any("no vendored skills found" in record.getMessage() for record in caplog.records)

    def test_logs_override_event(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """An override log event is emitted when a user skill displaces a vendored one."""
        import logging

        vendored_dir: Path = tmp_path / "vendored"
        user_dir: Path = tmp_path / "user_skills"
        _write_skill(directory=vendored_dir, slug="build-routers", name="build-routers")
        _write_skill(
            directory=user_dir,
            slug="build-routers",
            name="build-routers",
            description="Override",
        )

        with caplog.at_level(logging.INFO):
            SkillsLoader.load_merged(
                vendored_skills_dir=str(vendored_dir),
                user_skills_dir=str(user_dir),
                user_workflows_dir=str(tmp_path / "absent"),
            )

        assert any("user skill overrides vendored skill" in record.message for record in caplog.records)

    def test_both_sources_override_different_vendored_entries(self, tmp_path: Path) -> None:
        """User skills and user workflows can each override different vendored entries."""
        vendored_dir: Path = tmp_path / "vendored"
        user_dir: Path = tmp_path / "user_skills"
        workflows_dir: Path = tmp_path / "user_workflows"
        _write_skill(directory=vendored_dir, slug="skill-a", name="skill-a")
        _write_skill(directory=vendored_dir, slug="skill-b", name="skill-b")
        _write_skill(
            directory=user_dir,
            slug="skill-a",
            name="skill-a",
            description="User override A",
        )
        _write_skill(
            directory=workflows_dir,
            slug="skill-b",
            name="skill-b",
            description="User workflow override B",
        )

        result: list[SkillEntryDAO] = SkillsLoader.load_merged(
            vendored_skills_dir=str(vendored_dir),
            user_skills_dir=str(user_dir),
            user_workflows_dir=str(workflows_dir),
        )

        assert len(result) == 2
        by_name: dict[str, SkillEntryDAO] = {e.name: e for e in result}
        assert "user_skills" in by_name["skill-a"].file_path
        assert "user_workflows" in by_name["skill-b"].file_path

    def test_absence_of_user_dirs_is_not_an_error(self, tmp_path: Path) -> None:
        """load_merged does not raise when user dirs do not exist."""
        vendored_dir: Path = tmp_path / "vendored"
        _write_skill(directory=vendored_dir, slug="only-skill", name="only-skill")

        result: list[SkillEntryDAO] = SkillsLoader.load_merged(
            vendored_skills_dir=str(vendored_dir),
            user_skills_dir=str(tmp_path / "nonexistent_user"),
            user_workflows_dir=str(tmp_path / "nonexistent_workflows"),
        )

        assert len(result) == 1
        assert result[0].name == "only-skill"

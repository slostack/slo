"""Tests for ``SkillRegistry`` (sub-spec 01.l §7)."""

from __future__ import annotations

from pathlib import Path

from src.agents.skills.registry import Skill, SkillRegistry


def _write_skill(
    *,
    skills_dir: Path,
    relative_dir: str,
    name: str,
    description: str = "Use this skill when the task matches.",
    when_to_use: str = "Use when the task matches this skill.",
    group: str = "coding",
    kind: str = "skill",
    body: str = "# Skill body\n\nDetails go here.\n",
    frontmatter: str | None = None,
) -> Path:
    """Write a ``SKILL.md`` fixture and return its path."""
    skill_dir = skills_dir / relative_dir
    skill_dir.mkdir(parents=True, exist_ok=True)
    if frontmatter is None:
        frontmatter = (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"when_to_use: {when_to_use}\n"
            f"group: {group}\n"
            f"kind: {kind}\n"
            "---\n"
        )
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(frontmatter + body, encoding="utf-8")
    return skill_path


class TestSkillRegistry:
    """Behavioural tests for the dev-time skill registry."""

    class TestLoad:
        def test_returns_empty_when_dir_missing(self, tmp_path: Path) -> None:
            assert SkillRegistry.load(skills_dir=tmp_path / "nope") == []

        def test_loads_one_skill(self, tmp_path: Path) -> None:
            _write_skill(
                skills_dir=tmp_path,
                relative_dir="coding/build-routers",
                name="build-routers",
                description="Adding or modifying FastAPI endpoints.",
                when_to_use="Use when creating or changing HTTP routes.",
            )
            skills = SkillRegistry.load(skills_dir=tmp_path)
            assert len(skills) == 1
            assert skills[0].name == "build-routers"
            assert skills[0].description == "Adding or modifying FastAPI endpoints."
            assert skills[0].when_to_use == "Use when creating or changing HTTP routes."
            assert skills[0].group == "coding"
            assert skills[0].kind == "skill"
            assert skills[0].location.endswith("coding/build-routers/SKILL.md")

        def test_recurses_into_nested_directories(self, tmp_path: Path) -> None:
            _write_skill(
                skills_dir=tmp_path,
                relative_dir="design-and-analysis/feature-specifications",
                name="feature-specifications",
                group="design-and-analysis",
                kind="workflow",
            )
            skills = SkillRegistry.load(skills_dir=tmp_path)
            assert len(skills) == 1
            assert skills[0].location.endswith("design-and-analysis/feature-specifications/SKILL.md")

        def test_sorts_by_kind_then_group_then_name(self, tmp_path: Path) -> None:
            _write_skill(
                skills_dir=tmp_path,
                relative_dir="coding/build-routers",
                name="build-routers",
                group="coding",
                kind="skill",
            )
            _write_skill(
                skills_dir=tmp_path,
                relative_dir="orchestration/orchestrator",
                name="orchestrator",
                group="orchestration",
                kind="workflow",
            )
            _write_skill(
                skills_dir=tmp_path,
                relative_dir="coding/build-clients",
                name="build-clients",
                group="coding",
                kind="skill",
            )
            names = [skill.name for skill in SkillRegistry.load(skills_dir=tmp_path)]
            assert names == ["orchestrator", "build-clients", "build-routers"]

        def test_skips_skill_missing_frontmatter(self, tmp_path: Path) -> None:
            (tmp_path / "broken").mkdir()
            (tmp_path / "broken" / "SKILL.md").write_text("no frontmatter here\n")
            _write_skill(skills_dir=tmp_path, relative_dir="ok", name="ok")
            names = [skill.name for skill in SkillRegistry.load(skills_dir=tmp_path)]
            assert names == ["ok"]

        def test_skips_skill_missing_when_to_use(self, tmp_path: Path) -> None:
            _write_skill(
                skills_dir=tmp_path,
                relative_dir="no-when",
                name="no-when",
                frontmatter=(
                    "---\n"
                    "name: no-when\n"
                    "description: Missing routing hint.\n"
                    "group: coding\n"
                    "kind: skill\n"
                    "---\n"
                ),
            )
            _write_skill(skills_dir=tmp_path, relative_dir="ok", name="ok")
            names = [skill.name for skill in SkillRegistry.load(skills_dir=tmp_path)]
            assert names == ["ok"]

        def test_handles_yaml_block_strings(self, tmp_path: Path) -> None:
            _write_skill(
                skills_dir=tmp_path,
                relative_dir="block-desc",
                name="block-desc",
                frontmatter=(
                    "---\n"
                    "name: block-desc\n"
                    "description: >\n"
                    "  First line of the description.\n"
                    "  Second line continues.\n"
                    "when_to_use: >\n"
                    "  Use when the task is non-trivial.\n"
                    "  Load the detailed guidance before coding.\n"
                    "group: design-and-analysis\n"
                    "kind: workflow\n"
                    "---\n"
                ),
            )
            skills = SkillRegistry.load(skills_dir=tmp_path)
            assert len(skills) == 1
            assert skills[0].description == "First line of the description. Second line continues."
            assert skills[0].when_to_use == (
                "Use when the task is non-trivial. Load the detailed guidance before coding."
            )
            assert skills[0].group == "design-and-analysis"
            assert skills[0].kind == "workflow"

    class TestFormatForPrompt:
        def test_groups_skills_by_kind_and_group(self) -> None:
            skills = [
                Skill(
                    name="orchestrator",
                    description="Pick the next best skill.",
                    when_to_use="Use at the start of a task.",
                    group="orchestration",
                    kind="workflow",
                    location="skills/orchestration/orchestrator/SKILL.md",
                ),
                Skill(
                    name="build-routers",
                    description="Add or modify routes.",
                    when_to_use="Use when changing HTTP controllers.",
                    group="coding",
                    kind="skill",
                    location="skills/coding/build-routers/SKILL.md",
                ),
                Skill(
                    name="build-typer-cli-apps",
                    description="Build product CLIs.",
                    when_to_use="Use when changing src/cli.",
                    group="cli",
                    kind="skill",
                    location="skills/cli/build-typer-cli-apps/SKILL.md",
                ),
                Skill(
                    name="worktrees",
                    description="Parallel git work via worktrees.",
                    when_to_use="Use when the current tree must stay untouched.",
                    group="git-ops",
                    kind="skill",
                    location="skills/git-ops/worktrees/SKILL.md",
                ),
            ]
            out = SkillRegistry.format_for_prompt(skills=skills)
            assert "## Workflows" in out
            assert "### Orchestration" in out
            assert "**orchestrator**" in out
            assert "When to use: Use at the start of a task." in out
            assert "## Individual Skills" in out
            assert "### Coding" in out
            assert "### Git Ops" in out
            assert "### CLI" in out
            assert "skills/coding/build-routers/SKILL.md" in out

        def test_collapses_multiline_fields(self) -> None:
            skill = Skill(
                name="x",
                description="line one\n  line two   line three",
                when_to_use="use\n  this   skill",
                group="coding",
                kind="skill",
                location="skills/coding/x/SKILL.md",
            )
            out = SkillRegistry.format_for_prompt(skills=[skill])
            assert "line one line two line three" in out
            assert "When to use: use this skill" in out

        def test_empty_list_returns_just_newline(self) -> None:
            assert SkillRegistry.format_for_prompt(skills=[]) == "\n"

"""Repository-level assertions for the committed skills tree."""

from __future__ import annotations

from pathlib import Path

from src.agents.skills.registry import SkillRegistry

SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
EXPECTED_GROUPS: set[str] = {
    "design-and-analysis",
    "coding",
    "git-ops",
    "cli",
    "tui",
    "integration-tests",
    "frontend-vue",
    "orientation",
    "presentation",
    "user-content",
}
FORBIDDEN_SNIPPETS: tuple[str, ...] = (
    "/Users/",
    "file:///",
    "local_files/",
    "prompts/feature-requests/",
    "prompts/plans/",
    ".claude/projects/",
)


class TestCommittedSkills:
    """Guardrails for the committed, runtime-visible skills catalog."""

    def test_every_committed_skill_loads(self) -> None:
        skills = SkillRegistry.load(skills_dir=SKILLS_DIR)
        names = {skill.name for skill in skills}
        assert "orchestrator" in names
        assert "implement-feature-request" in names
        assert "generate-agents-md" in names
        assert "generate-research-md" in names
        assert "agents" in names
        assert "readme" in names
        assert "cli-readme" in names
        assert "tui-readme" in names
        assert "git-ops-orchestrator" in names
        assert "sync-main" in names
        assert "create-feature-branch" in names
        assert "commit-and-push" in names
        assert "generate-pr-description" in names
        assert "create-pull-request" in names
        assert "load-pr-context" in names
        assert "fix-pr-review" in names
        assert "worktrees" in names
        assert "tui-scheduled-operations" in names
        assert "tui-scheduled-workflows" in names

    def test_top_level_group_directories_exist(self) -> None:
        groups = {path.name for path in SKILLS_DIR.iterdir() if path.is_dir()}
        assert groups == EXPECTED_GROUPS

    def test_every_skill_has_standard_sections(self) -> None:
        for skill_file in sorted(SKILLS_DIR.rglob("SKILL.md")):
            text = skill_file.read_text(encoding="utf-8")
            assert "## Skill summary" in text, skill_file.as_posix()
            assert "## Examples" in text, skill_file.as_posix()
            assert "## Guidance" in text, skill_file.as_posix()

    def test_committed_skills_live_under_their_group_directory(self) -> None:
        for skill in SkillRegistry.load(skills_dir=SKILLS_DIR):
            expected_prefix = f"skills/{skill.group}/"
            assert skill.location.startswith(expected_prefix)

    def test_committed_skills_do_not_contain_local_machine_paths(self) -> None:
        for skill_file in sorted(SKILLS_DIR.rglob("SKILL.md")):
            text = skill_file.read_text(encoding="utf-8")
            for snippet in FORBIDDEN_SNIPPETS:
                assert snippet not in text, f"{skill_file}: found forbidden snippet {snippet!r}"

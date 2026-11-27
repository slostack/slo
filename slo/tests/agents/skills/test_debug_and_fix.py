"""Discovery and safety contracts for the project-agnostic debugging skill."""

from pathlib import Path
import re

from scripts.build_skill_index import _INDEX_HEADER
from src.agents.skills.registry import SkillRegistry
from src.agents.slo_agent.skills.service import SkillsLoader

SKILLS_DIR: Path = Path(__file__).resolve().parents[3] / "skills"
SKILL_PATH: Path = SKILLS_DIR / "coding/debug-and-fix/SKILL.md"


def test_debug_and_fix_is_discovered_and_indexed(tmp_path: Path) -> None:
    """Both real discovery consumers expose one invocable coding skill."""
    catalog = SkillRegistry.load(skills_dir=SKILLS_DIR)
    matches = [entry for entry in catalog if entry.name == "debug-and-fix"]
    assert len(matches) == 1
    assert matches[0].group == "coding"
    assert matches[0].kind == "skill"
    assert matches[0].location == "skills/coding/debug-and-fix/SKILL.md"
    runtime = SkillsLoader.load_merged(
        vendored_skills_dir=str(SKILLS_DIR),
        user_skills_dir=str(tmp_path / "user_skills"),
        user_workflows_dir=str(tmp_path / "user_workflows"),
    )
    discovered = [entry for entry in runtime if entry.name == "debug-and-fix"]
    assert len(discovered) == 1
    assert discovered[0].file_path == str(SKILL_PATH)
    assert discovered[0].disable_model_invocation is False
    assert (SKILLS_DIR / "INDEX.md").read_text(encoding="utf-8") == (
        _INDEX_HEADER + SkillRegistry.format_for_prompt(skills=catalog)
    )


def test_debug_and_fix_preserves_permission_privacy_and_verification_contracts() -> None:
    """Guidance retains the safety gates and links readers to canonical owners."""
    body: str = SKILL_PATH.read_text(encoding="utf-8")
    text: str = " ".join(body.split())
    for required in (
        "## Skill summary",
        "## Examples",
        "## Guidance",
        "already granted",
        "diagnosis",
        "remediation",
        "before normalization",
        "original exception types",
        "stack locations",
        "structural reason",
        "correlation IDs",
        "no secrets",
        "raw payloads",
        "reasoning content",
        "INFO",
        "DEBUG",
        "ERROR",
        "RED",
        "GREEN",
        "integrations",
        "no regressions",
        "terminal response",
        "never fire-and-forget",
        "background",
        "singleton ownership",
        "graceful shutdown",
        "authorized escalation",
        "stale pollers",
        "blind tool replay",
        "incomplete success",
        "SLO_DEV_MODE=1 poetry run python -m src.cli --resume <session_id>",
    ):
        assert required in text, required
    assert "SLO_DEV_MOVE" not in body
    for destination in re.findall(r"\]\(([^)]+)\)", body):
        assert (SKILL_PATH.parent / destination).is_file(), destination

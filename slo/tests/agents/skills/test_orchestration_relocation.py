"""Feature 95 move-only discovery and preservation contracts."""

import hashlib
from pathlib import Path

import pytest

from src.agents.skills.registry import SkillRegistry
from src.agents.slo_agent.skills.service import SkillsLoader
from src.agents.slo_agent.prompts import SystemPromptBuilder

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "skills"
NAMES = ("orchestrator", "workflows", "headless-orchestration")


def test_frozen_moves_normalize_to_base_bytes() -> None:
    """Freeze preserved owners; convergence policy revisions have semantic gates."""
    # Code-test-review, its GitLab companion and workflow orchestration now intentionally
    # evolve under test_workflow_convergence.py and the progression/turn-rule suites.
    # The specification workflow now evolves under the semantic gates in
    # test_specification_authoring.py. The orchestrator pin was re-taken when its
    # specification routing moved to overview → sub-specs → family review.
    pins = {
        "skills/orchestration/orchestrator/SKILL.md": "79537a28e721f11c7773fd381b599fdba39c1611ac7b04fc0d97bbd598737606",
    }
    for relative, expected in pins.items():
        text = (ROOT / relative).read_text()
        for name in NAMES:
            text = text.replace(f"skills/orchestration/{name}/", f"skills/design-and-analysis/{name}/")
        text = text.replace("group: orchestration\n", "group: design-and-analysis\n")
        assert hashlib.sha256(text.encode()).hexdigest() == expected


def test_headless_followup_preserves_metadata() -> None:
    """The user exception covers only this body, never discovery metadata."""
    text = (SKILLS / "orchestration/headless-orchestration/SKILL.md").read_text()
    metadata = text.split("---", 2)[1]
    assert (
        hashlib.sha256(metadata.encode()).hexdigest()
        == "89f93373c5641b4fc7f7f5c50b45700ba01e8598363cef79b6a2ee1992fd277e"
    )


def test_registry_group_order_and_documented_roster() -> None:
    """The new group follows design-and-analysis and the documented count is current."""
    entries = SkillRegistry.load(skills_dir=SKILLS)
    rendered = SkillRegistry.format_for_prompt(skills=entries).split("## Individual Skills")[1]
    assert rendered.index("### Design and Analysis") < rendered.index("### Orchestration")
    assert rendered.index("### Orchestration") < rendered.index("### Coding")
    text = (ROOT / "README.md").read_text()
    assert f"{len(entries)} skills across 14 groups" in text


@pytest.mark.parametrize("name", NAMES)
def test_runtime_manifest_and_override_precedence(name: str, tmp_path: Path) -> None:
    """Real three-tier merging retains identity and renders the winning absolute path."""
    expected = SKILLS / "orchestration" / name / "SKILL.md"
    for tier in ("vendored", "user", "workflow"):
        if tier != "vendored":
            expected = tmp_path / tier / name / "SKILL.md"
            assert expected.resolve().is_relative_to(tmp_path.resolve())
            expected.parent.mkdir(parents=True)
            expected.write_text(f"---\nname: {name}\ndescription: {tier} override\n---\n")
        entries = SkillsLoader.load_merged(
            vendored_skills_dir=str(SKILLS),
            user_skills_dir=str(tmp_path / "user"),
            user_workflows_dir=str(tmp_path / "workflow"),
        )
        selected = [entry for entry in entries if entry.name == name]
        assert len(selected) == 1
        assert selected[0].file_path == str(expected)
        assert str(expected) in SystemPromptBuilder._format_skills_as_xml(skills=selected)


@pytest.mark.parametrize("name", NAMES)
def test_relocated_identity_and_group(name: str) -> None:
    """Real dev and runtime discovery agree on each unique relocated identity."""
    location = f"skills/orchestration/{name}/SKILL.md"
    registered = [entry for entry in SkillRegistry.load(skills_dir=SKILLS) if entry.name == name]
    runtime = [entry for entry in SkillsLoader.load(skills_dir=str(SKILLS)) if entry.name == name]
    assert len(registered) == len(runtime) == 1
    assert registered[0].location == location
    assert registered[0].group == "orchestration"
    assert runtime[0].file_path == str(ROOT / location)
    assert not (SKILLS / "design-and-analysis" / name).exists()


def test_excluded_tui_skills_preserve_body_except_repaired_reference() -> None:
    """Retain base 7625be3 pins, normalizing only the authorized dangling-link repair."""
    pins = {
        "tui-scheduled-workflows": "ca00e36826f5e12d986df4079c3a6f10081b1a0cd92a174ab9b77d68290286de",
        "tui-scheduled-operations": "9315d9d5bdd8a32cfed188bae4ff8edd86bf5d5023654cf46343897e6215a869",
    }
    for name, expected in pins.items():
        text = (SKILLS / "tui" / name / "SKILL.md").read_text(encoding="utf-8")
        if name == "tui-scheduled-workflows":
            current = "skills/orchestration/headless-orchestration/SKILL.md"
            obsolete = "skills/design-and-analysis/headless-orchestration/SKILL.md"
            assert current in text and obsolete not in text
            text = text.replace(current, obsolete)
        assert hashlib.sha256(text.encode()).hexdigest() == expected

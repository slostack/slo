"""Regression contracts for the additive design skills."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.agents.slo_agent.skills.service import SkillsLoader

ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = ROOT / "skills"
CODE_DESIGN_PATH = SKILLS_DIR / "coding/code-design-principles/SKILL.md"
SOLUTION_DESIGN_PATH = SKILLS_DIR / "coding/solution-design/SKILL.md"
FEATURE_SPECIFICATION_PATH = SKILLS_DIR / "design-and-analysis/feature-specifications/SKILL.md"
REQUIRED_SKILL_SECTIONS = ("## Skill summary", "## Examples", "## Guidance")
REQUIRED_FRONTMATTER_FIELDS = {"name", "description", "when_to_use", "group", "kind"}


def _skill_parts(path: Path) -> tuple[dict[str, object], str]:
    """Return parsed frontmatter and authored body for a skill file."""
    text = path.read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    assert isinstance(metadata, dict)
    return metadata, body


def test_design_skills_have_distinct_identities_and_required_contract() -> None:
    """The two additive skills remain separate, invocable, and structurally complete."""
    code_metadata, code_body = _skill_parts(path=CODE_DESIGN_PATH)
    solution_metadata, solution_body = _skill_parts(path=SOLUTION_DESIGN_PATH)

    assert code_metadata["name"] == "code-design-principles"
    assert solution_metadata["name"] == "solution-design"
    assert code_metadata["name"] != solution_metadata["name"]
    for metadata, body in ((code_metadata, code_body), (solution_metadata, solution_body)):
        assert REQUIRED_FRONTMATTER_FIELDS <= set(metadata)
        assert metadata["group"] == "coding"
        assert metadata["kind"] == "skill"
        assert metadata.get("disable-model-invocation") is not True
        for section in REQUIRED_SKILL_SECTIONS:
            assert section in body


def test_generic_examples_are_explicitly_illustrative() -> None:
    """Generic examples teach concepts without pretending to be production or universal syntax."""
    code_text = CODE_DESIGN_PATH.read_text(encoding="utf-8")
    naming_text = (SKILLS_DIR / "coding/naming-and-clarity/SKILL.md").read_text(encoding="utf-8")
    verification_text = (SKILLS_DIR / "coding/test-verification-policy/SKILL.md").read_text(encoding="utf-8")

    assert "illustrative examples" in code_text
    assert "not copied production code" in naming_text
    assert "Python decision-path illustration" in verification_text


def test_solution_design_preserves_source_inputs_and_reconstructed_fidelity_limits() -> None:
    """Design work names supplied inputs and labels incomplete source fidelity honestly."""
    text = SOLUTION_DESIGN_PATH.read_text(encoding="utf-8")
    normalized_text = " ".join(text.split())

    assert "Keep all supplied paths in the design's sources section" in text
    assert "source artifacts, plans, ledgers, and review notes" in normalized_text
    assert "incomplete or reconstructed" in normalized_text
    assert "do not imply byte-for-byte fidelity" in normalized_text


def test_code_design_principles_has_python_go_and_typescript_examples() -> None:
    """The generic design guidance demonstrates its rules in all three supported languages."""
    _, text = _skill_parts(path=CODE_DESIGN_PATH)

    expected_examples = {
        "### Python": ("class ReceiptStore:", "load_or_create"),
        "### Go": ("func (s *ReceiptStore) LoadOrCreate", "context.Context"),
        "### TypeScript": ("async loadOrCreate", "Promise<Receipt>"),
    }
    for heading, markers in expected_examples.items():
        assert heading in text
        section_start = text.index(heading)
        next_heading = text.find("\n### ", section_start + len(heading))
        section = text[section_start:] if next_heading == -1 else text[section_start:next_heading]
        for marker in markers:
            assert marker in section, (heading, marker)


def test_merged_runtime_discovery_exposes_both_design_skills(tmp_path: Path) -> None:
    """The real merged loader discovers both vendored skills without providers or network access."""
    entries = SkillsLoader.load_merged(
        vendored_skills_dir=str(SKILLS_DIR),
        user_skills_dir=str(tmp_path / "user_skills"),
        user_workflows_dir=str(tmp_path / "user_workflows"),
    )
    entries_by_name = {entry.name: entry for entry in entries}

    assert entries_by_name["code-design-principles"].file_path == str(CODE_DESIGN_PATH)
    assert entries_by_name["solution-design"].file_path == str(SOLUTION_DESIGN_PATH)
    assert entries_by_name["code-design-principles"].disable_model_invocation is False
    assert entries_by_name["solution-design"].disable_model_invocation is False
    assert [entry.name for entry in entries].count("code-design-principles") == 1
    assert [entry.name for entry in entries].count("solution-design") == 1


def test_feature_specification_references_canonical_design_prerequisites() -> None:
    """Feature specifications name the shared rules and the optional design companion explicitly."""
    text = FEATURE_SPECIFICATION_PATH.read_text(encoding="utf-8")

    assert "[coding rules](../../coding/coding-rules/SKILL.md)" in text
    assert "[code design principles](../../coding/code-design-principles/SKILL.md)" in text
    assert "[solution design](../../coding/solution-design/SKILL.md)" in text
    assert "optional companion" in text
    assert "not mandatory for every feature specification" in text


def test_solution_design_requires_consent_and_forbids_implicit_implementation() -> None:
    """Solution design remains a design-only skill unless the user separately authorizes implementation."""
    text = SOLUTION_DESIGN_PATH.read_text(encoding="utf-8")

    assert "Explore alternatives with sub-agents" in text
    assert "only when the user explicitly requests" in text
    assert "alternative interfaces and explicitly authorizes sub-agents" in " ".join(text.split())
    assert "alternative interfaces with sub-agents: yes/no" in text
    assert "Without explicit sub-agent permission" in text
    assert "not an implementation" in text
    assert "plan to execute automatically" in text
    normalized_text = " ".join(text.split())
    assert "do not implement code, write tests, edit wiring, or alter related documents" in normalized_text
    assert "unless the user separately asks for that work" in normalized_text

"""Language-neutral discovery contracts for the on-request companion."""

from pathlib import Path

import pytest
import yaml

PATH = Path(__file__).resolve().parents[3] / "skills/design-and-analysis/gather-feature-context/SKILL.md"


def test_source_status_and_scope() -> None:
    """Source absence is not negative evidence; product scope is not hard-coded."""
    text = PATH.read_text()
    metadata = yaml.safe_load(text.split("---")[1])
    assert metadata["name"] == "gather-feature-context"
    assert metadata["group"] == "design-and-analysis"
    assert metadata["kind"] == "workflow"
    for phrase in ("consulted-with-findings", "unavailable", "empty", "contradictions"):
        assert phrase in text
    for source in ("Knowledge base", "Jira / Confluence", "Code", "Documentation / READMEs", "Tests"):
        assert f"| {source} |" in text
    assert "orders_service" not in text
    assert "not a second default pre-hook" in text
    assert "Stop here and wait for user sign-off" in text


@pytest.mark.parametrize("language", ("Python", "Go", "TypeScript"))
def test_language_discovery_is_not_architecture(language: str) -> None:
    """Each guide covers non-web entry points without imposing new layers."""
    text = PATH.read_text()
    section = text.split(f"### {language}\n")[1].split("### ")[0]
    for phrase in ("discovery guide, not a mandated architecture", "CLI", "worker", "event-driven", "tests"):
        assert phrase in section


def test_schema_and_behavior_map() -> None:
    """The verified-schema gate and evidence-backed briefing survive generalization."""
    text = PATH.read_text()
    for phrase in (
        "ORM model",
        "migration directory",
        "schema definition",
        "protobuf",
        "Behavior map",
        "Source status",
        "contradictions",
        "stop and surface",
    ):
        assert phrase in text
    assert "psql -h" not in text
    assert "BigQuery" not in text
    assert "SQLAlchemy model file" not in text

"""Published workflow rules distinguish full passes from agent dispatches."""

from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[3] / "skills"
RULE_PATH = "skills/orchestration/workflows/SKILL.md#workflow-turns-and-limits"


def test_shared_rules_define_turns_and_partial_progress() -> None:
    text = (SKILLS / "orchestration/workflows/SKILL.md").read_text()
    for phrase in (
        "## Workflow turns and limits",
        "complete pass through all the stages",
        "A dispatch is not a workflow turn",
        "The default 60 turns started includes partial turns",
        "partial turn",
        "phase retries",
        "20 dispatch calls per workflow turn",
        "Do not bypass a harness limit",
        "independent review",
    ):
        assert phrase in text


@pytest.mark.parametrize(
    "relative",
    (
        "orchestration/orchestrator/SKILL.md",
        "orchestration/headless-orchestration/SKILL.md",
        "orchestration/workflows/code-test-review.md",
        "orchestration/workflows/specification-development.md",
        "orchestration/workflows/gitlab-code-test-review.md",
    ),
)
def test_workflow_and_orchestrator_entries_link_shared_turn_rules(relative: str) -> None:
    text = (SKILLS / relative).read_text()
    assert RULE_PATH in text
    assert "Explicit user instructions override" in text
    assert "raise, lower or remove" in text

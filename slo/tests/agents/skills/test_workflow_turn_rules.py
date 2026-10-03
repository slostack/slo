"""Published workflow rules distinguish full passes from agent dispatches."""

from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[3] / "skills"
RULE_PATH = "skills/design-and-analysis/workflows/SKILL.md#workflow-turns-and-limits"


def test_shared_rules_define_turns_and_partial_progress() -> None:
    text = (SKILLS / "design-and-analysis/workflows/SKILL.md").read_text()
    for phrase in (
        "## Workflow turns and limits",
        "complete pass through all the stages",
        "A dispatch is not a workflow turn",
        "Eight turns started includes partial turns",
        "partial turn",
        "phase retries",
        "6 dispatch calls per workflow turn",
        "Do not bypass a harness limit",
        "independent review",
    ):
        assert phrase in text


@pytest.mark.parametrize(
    "relative",
    (
        "design-and-analysis/orchestrator/SKILL.md",
        "design-and-analysis/headless-orchestration/SKILL.md",
        "design-and-analysis/workflows/code-test-review.md",
        "design-and-analysis/workflows/specification-development.md",
        "design-and-analysis/workflows/gitlab-code-test-review.md",
    ),
)
def test_workflow_and_orchestrator_entries_link_shared_turn_rules(relative: str) -> None:
    assert RULE_PATH in (SKILLS / relative).read_text()

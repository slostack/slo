"""Keep commit instructions and examples aligned with the user's footer."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "relative",
    (
        "AGENTS.md",
        "SLO.md",
        "CLAUDE.md",
        "skills/git-ops/branching-and-commit-conventions/SKILL.md",
        "skills/git-ops/ship-feature/SKILL.md",
        "skills/design-and-analysis/workflows/gitlab-code-test-review.md",
    ),
)
def test_commit_instructions_use_slo_footer(relative: str) -> None:
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert "--developed with Slo" in text
    assert "Co-Authored-By: Claude" not in text
    assert "noreply@anthropic.com" not in text

"""Keep commit guidance aligned with the repository-owned attribution policy.

The original regression asserted a ``--developed with Slo`` phrase that appears
in one historical commit message, not in the current instructions.  Latest main
makes the AI attribution contract explicit in the git-ops examples: use the
canonical ``Co-Authored-By`` trailer.  These checks prevent the historical phrase
from being reintroduced and verify the exact trailer where commit examples teach it.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CURRENT_AI_FOOTER = "Co-Authored-By: Claude <noreply@anthropic.com>"
POLICY_FILES = (
    "README.md",
    "SLO.md",
    "skills/git-ops/branching-and-commit-conventions/SKILL.md",
    "skills/git-ops/ship-feature/SKILL.md",
    "skills/orchestration/workflows/gitlab-code-test-review.md",
)
COMMIT_EXAMPLE_FILES = (
    "skills/git-ops/branching-and-commit-conventions/SKILL.md",
    "skills/git-ops/ship-feature/SKILL.md",
    "skills/orchestration/workflows/gitlab-code-test-review.md",
)


@pytest.mark.parametrize("relative", POLICY_FILES)
def test_commit_instructions_do_not_claim_historical_slo_footer(relative: str) -> None:
    """Reject the historical attribution phrase in every policy surface."""
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert "--developed with Slo" not in text


@pytest.mark.parametrize("relative", COMMIT_EXAMPLE_FILES)
def test_commit_examples_use_canonical_ai_footer(relative: str) -> None:
    """Require commit examples to teach the exact repository-approved trailer."""
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert CURRENT_AI_FOOTER in text

"""Documentary gates for bounded, evidence-driven implementation workflows."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "skills"


@pytest.mark.parametrize(
    argnames=("relative", "required"),
    argvalues=(
        (
            "orchestration/workflows/code-test-review.md",
            ("Acceptance contract", "Runnable", "Acceptance-ready", "Early integration feedback"),
        ),
        (
            "coding/code-test-loop/SKILL.md",
            ("observable behavior", "incorrect test oracle", "existing evidence"),
        ),
        (
            "engineering/engineering-testing/SKILL.md",
            ("Requirement-and-risk map", "Cartesian product", "baseline", "harness"),
        ),
        (
            "coding/test-verification-policy/SKILL.md",
            ("existing tests", "pure delegation", "forbidden effects"),
        ),
        (
            "languages/typescript/typescript-code-review-rules/SKILL.md",
            (
                "skills/coding/test-verification-policy/SKILL.md",
                "typescript-test-verification-policy/SKILL.md",
                "One behavioral test may traverse several branches",
                "not a test-count formula",
                "critical failure paths",
                "explicit specification matrices",
                "existing tests",
                "forbidden effects",
                "unverified",
                "explicit approval",
            ),
        ),
        (
            "design-and-analysis/review-feature-code/SKILL.md",
            ("closure condition", "stable IDs", "Early integration feedback"),
        ),
        (
            "orchestration/workflows/SKILL.md",
            ("Convergence checkpoint", "three continuations", "not an execution cap", "closure target"),
        ),
        (
            "engineering/engineering-routing/SKILL.md",
            ("Continuation", "invalidate", "authoritative guidance"),
        ),
        (
            "design-and-analysis/is-the-feature-completed/SKILL.md",
            ("Unverified", "original specification", "explicit deferral", "READY"),
        ),
    ),
)
def test_convergence_owners_publish_their_contract(relative: str, required: tuple[str, ...]) -> None:
    """Each owner publishes the agreed responsibility without relying on conversation history."""
    text = (SKILLS / relative).read_text(encoding="utf-8")
    for phrase in required:
        assert phrase in text, (relative, phrase)


def test_workflow_keeps_acceptance_and_independent_review_after_runnable_milestone() -> None:
    """A walking skeleton and advisory feedback cannot substitute for final acceptance."""
    text = (SKILLS / "orchestration/workflows/code-test-review.md").read_text(encoding="utf-8")
    assert text.index("### Runnable") < text.index("### Early integration feedback")
    assert text.index("### Early integration feedback") < text.index("### Acceptance-ready")
    assert text.index("### Acceptance-ready") < text.index("## Step 2") < text.index("## Step 3")
    for phrase in ("independent", "explicit approval", "no regressions", "retest and re-review"):
        assert phrase in text


def test_convergence_does_not_create_a_hidden_budget_or_review_bypass() -> None:
    """The checkpoint changes strategy, not the user's limits or the evidence gates."""
    text = (SKILLS / "orchestration/workflows/SKILL.md").read_text(encoding="utf-8")
    section = text.split("### Convergence checkpoint", 1)[1].split("\n## ", 1)[0]
    for phrase in (
        "not an execution cap",
        "unlimited",
        "do not reset",
        "independent review",
        "closure target",
    ):
        assert phrase in section


@pytest.mark.parametrize(
    argnames="relative",
    argvalues=(
        "orchestration/workflows/code-test-review.md",
        "orchestration/workflows/gitlab-code-test-review.md",
        "coding/code-test-loop/SKILL.md",
        "coding/test-verification-policy/SKILL.md",
        "languages/python/code-review-rules/SKILL.md",
        "languages/typescript/typescript-code-test-loop/SKILL.md",
        "languages/typescript/typescript-code-review-rules/SKILL.md",
        "languages/typescript/typescript-test-verification-policy/SKILL.md",
    ),
)
def test_related_owners_do_not_reintroduce_mechanical_cadence(relative: str) -> None:
    """Language and GitLab companions cannot silently restore the removed mandates."""
    text = (SKILLS / relative).read_text(encoding="utf-8")
    for obsolete in (
        "~50 lines",
        "each test should exercise exactly one branch",
        "implement one private method",
        "Resist the urge to run the tests first",
        "must have at least one dedicated test",
        "each decision point gets its own test",
        "Every decision point (if/switch/guard/catch) has a test",
    ):
        assert obsolete not in text, (relative, obsolete)


def test_completion_uses_evidence_not_weighted_percentages() -> None:
    """A high completion score cannot hide an unverified acceptance requirement."""
    text = (SKILLS / "design-and-analysis/is-the-feature-completed/SKILL.md").read_text(encoding="utf-8")
    assert "Partial count * 0.5" not in text
    assert "cannot establish readiness" in text
    assert "source" in text and "closure condition" in text

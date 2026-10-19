"""Regression contracts for readable, complete specification prompts."""

from pathlib import Path
import re

import pytest

SKILLS = Path(__file__).resolve().parents[3] / "skills"
AUTHOR = "design-and-analysis/feature-specifications/SKILL.md"
REVIEW = "design-and-analysis/feature-specification-verification/SKILL.md"
BREAKDOWN = "design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md"
WORKFLOW = "orchestration/workflows/specification-development.md"
SAMPLE = "samples/implementation-details-granularity.md"


@pytest.mark.parametrize("relative", [AUTHOR, REVIEW, BREAKDOWN, WORKFLOW, SAMPLE])
def test_active_specification_guidance_has_no_expansion_mandates(relative: str) -> None:
    """Do not restore conflicting chapter, numbering, or full-listing mandates."""
    text = (SKILLS / relative).read_text(encoding="utf-8")
    for obsolete in (
        "O'Reilly",
        "## 7. Implementation Details",
        "## 10. Dependencies",
        "full corrected class listings",
        "Prefer complete implementations over snippets",
        "every code sample from the source spec",
        "Silent prose is banned",
    ):
        assert obsolete not in text, (relative, obsolete)


def test_author_defines_complete_contracts_without_duplicate_narrative() -> None:
    """Keep semantic completeness, explicit ownership, and proposed/source separation."""
    text = (SKILLS / AUTHOR).read_text(encoding="utf-8")
    for requirement in (
        "### Engineering sub-spec structure",
        "### File-by-file implementation contracts",
        "### Existing behavior versus proposed contracts",
        "### Single-source contracts",
        "### Revision and evidence hygiene",
        "### Presentation rules",
        "requiredness, nullability, defaults",
        "Do not replace fields, parameters, enum members, or defaults with ellipses",
        "Method bodies may be omitted",
        "no arbitrary word limit",
        "independent verification",
    ):
        assert requirement in text


def test_review_checks_semantic_preservation_not_fixed_heading_count() -> None:
    """Shortening must preserve failure, compatibility, and acceptance contracts."""
    text = (SKILLS / REVIEW).read_text(encoding="utf-8")
    for requirement in (
        "Accept combined or renamed sections",
        "requiredness, nullability, defaults",
        "atomicity, concurrency, and idempotency",
        "Compatibility and migration",
        "competing versions",
        "CRITICAL",
        "independent verification",
    ):
        assert requirement in text


def test_breakdown_and_workflow_preserve_ownership_and_review_gates() -> None:
    """Task generation must not re-expand contracts or bypass review after edits."""
    breakdown = (SKILLS / BREAKDOWN).read_text(encoding="utf-8")
    workflow = (SKILLS / WORKFLOW).read_text(encoding="utf-8")
    assert "Preserve semantic coverage" in breakdown
    assert "Material contract changes require renewed verification" in breakdown
    assert "final editorial pass" in workflow
    assert "workflow records outside the specification body" in workflow
    assert "independent, adversarial review" in workflow


def test_sample_demonstrates_overview_contract_and_verifiable_python() -> None:
    """The shipped example must demonstrate—not just describe—the new format."""
    text = (SKILLS / SAMPLE).read_text(encoding="utf-8")
    for requirement in (
        "## Overview sample",
        "## Engineering sub-spec sample",
        "Required-but-nullable",
        "Transaction ownership",
        "Cross-field invariant",
        "Consumer boundary",
        "test_replace_when_revision_conflicts",
        "No tests have been run",
    ):
        assert requirement in text
    blocks = re.findall(pattern=r"```python\n(.*?)\n```", string=text, flags=re.DOTALL)
    assert len(blocks) >= 3
    for index, block in enumerate(blocks):
        compile(source=block, filename=f"sample-block-{index}", mode="exec")


def test_sample_dto_preserves_required_nullable_and_cross_field_validation() -> None:
    """Execute the sample's self-contained schema instead of trusting its prose."""
    text = (SKILLS / SAMPLE).read_text(encoding="utf-8")
    block = re.findall(pattern=r"```python\n(.*?)\n```", string=text, flags=re.DOTALL)[0]
    namespace: dict = {}
    exec(compile(source=block, filename="sample-dao", mode="exec"), namespace)
    from pydantic import ValidationError

    request_type = namespace["ReplaceNoteDAO"]
    assert request_type.model_fields["reason"].is_required()
    assert request_type(expected_revision=0, text="hello", archived=False, reason=None).reason is None
    with pytest.raises(ValidationError):
        request_type(expected_revision=0, text="hello", archived=False)
    with pytest.raises(ValidationError):
        request_type(expected_revision=0, text="hello", archived=True, reason=None)
    with pytest.raises(ValidationError):
        request_type(expected_revision=True, text="hello", archived=False, reason=None)
    with pytest.raises(ValidationError):
        request_type(expected_revision=0, text="hello", archived=False, reason=None, extra="bad")

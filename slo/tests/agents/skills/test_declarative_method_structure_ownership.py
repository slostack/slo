"""Focused ownership and preservation checks for declarative method skills."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
GENERIC = ROOT / "skills/coding/declarative-method-structure/SKILL.md"
PYTHON = ROOT / "skills/languages/python/declarative-method-structure/SKILL.md"
GO = ROOT / "skills/languages/go/go-declarative-method-structure/SKILL.md"
TYPESCRIPT = ROOT / "skills/languages/typescript/typescript-declarative-method-structure/SKILL.md"


def test_generic_owner_retains_meaningful_patterns_and_usable_companion_examples() -> None:
    """The generic owner contains teaching content rather than orphan headings."""
    text = GENERIC.read_text(encoding="utf-8")

    for phrase in (
        "Pattern: Nested conditionals",
        "Pattern: validation chains",
        "Pattern: strategy/command with lookup tables",
        "Pattern: Tell, Don't Ask with services",
        "Pattern: polymorphism over conditionals",
        "Pattern: orchestrators read like a table of contents",
        "## Testing benefits and decision-path examples",
        "# email_service.py — a usable companion example",
        "class NotificationHandler(ABC):",
        "async def assess_node(state: AgentState) -> dict:",
        "## Review checklist",
    ):
        assert phrase in text

    assert "# Concrete handlers" not in text
    assert "# Coordinator\n" not in text


def test_specializations_keep_only_language_specific_contracts_and_reference_owner() -> None:
    """Specializations point to the generic owner without copying its patterns."""
    generic_pattern_headings = (
        "Pattern: Nested conditionals",
        "Pattern: validation chains",
        "Pattern: strategy/command with lookup tables",
        "Pattern: polymorphism over conditionals",
        "Pattern: orchestrators read like a table of contents",
    )
    for path, requirements in (
        (
            PYTHON,
            (
                "Google-style docstrings",
                "keyword arguments",
                "approximately **8 lines of substantive logic**",
                "collections.abc",
            ),
        ),
        (
            GO,
            (
                "Execute(ctx, in)",
                "consumer-local interfaces",
                "errors.Is",
                "approximately **15 lines of substantive logic or fewer**",
            ),
        ),
        (
            TYPESCRIPT,
            (
                "Record<K, Handler>",
                "discriminated unions",
                "exhaustive `never` checks",
                "approximately **8 lines of substantive logic**",
            ),
        ),
    ):
        text = path.read_text(encoding="utf-8")
        assert "skills/coding/declarative-method-structure/SKILL.md" in text
        for heading in generic_pattern_headings:
            assert heading not in text
        for requirement in requirements:
            assert requirement in text


def test_python_specialization_does_not_repeat_generic_core_principles() -> None:
    """Python-specific guidance does not recreate the removed generic teaching section."""
    text = PYTHON.read_text(encoding="utf-8")
    assert "## Core Principles" not in text
    assert "### 1. Single Decision Per Method" not in text
    assert text.count("approximately **8 lines of substantive logic**") == 1

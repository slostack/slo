"""Tests for the Kimi-for-coding task-prompt clause."""

from __future__ import annotations

import pytest

from src.agents.model_catalog.prompt_clause import append_kimi_for_coding_clause


class TestAppendKimiForCodingClause:
    """Exact-match guardrails for the Kimi clause."""

    def test_appends_clause_for_exact_kimi_for_coding(self) -> None:
        """The clause is appended when the model is exactly kimi-for-coding."""
        result: str = append_kimi_for_coding_clause(
            prompt="Implement the feature.",
            model_name="kimi-for-coding",
        )

        assert "Be succinct and terse" in result
        assert result.startswith("Implement the feature.")

    def test_no_clause_for_kimi_k3(self) -> None:
        """kimi-k3 does not receive the clause."""
        result: str = append_kimi_for_coding_clause(
            prompt="Implement the feature.",
            model_name="kimi-k3",
        )

        assert result == "Implement the feature."

    def test_no_clause_for_kimi_for_coding_highspeed(self) -> None:
        """kimi-for-coding-highspeed does not receive the clause."""
        result: str = append_kimi_for_coding_clause(
            prompt="Implement the feature.",
            model_name="kimi-for-coding-highspeed",
        )

        assert result == "Implement the feature."

    def test_no_clause_for_non_kimi_model(self) -> None:
        """Non-Kimi models do not receive the clause."""
        result: str = append_kimi_for_coding_clause(
            prompt="Implement the feature.",
            model_name="gpt-5.5",
        )

        assert result == "Implement the feature."

    def test_no_duplicate_clause(self) -> None:
        """The clause is not duplicated if the prompt already contains it."""
        original: str = append_kimi_for_coding_clause(
            prompt="Implement the feature.",
            model_name="kimi-for-coding",
        )
        result: str = append_kimi_for_coding_clause(
            prompt=original,
            model_name="kimi-for-coding",
        )

        assert result.count("Be succinct and terse") == 1

"""Unit tests for in-process prompt-history recall."""

from __future__ import annotations

from src.tui.prompt_history import PromptHistoryNavigator


class TestPromptHistoryNavigator:
    """Older/newer prompt recall semantics."""

    def test_older_returns_entries_in_reverse_submission_order(self) -> None:
        """Older recall walks backward through recorded prompts."""
        navigator: PromptHistoryNavigator = PromptHistoryNavigator()
        navigator.record(text="first prompt")
        navigator.record(text="second prompt")

        assert navigator.older(current_buffer="") == "second prompt"
        assert navigator.older(current_buffer="") == "first prompt"
        assert navigator.older(current_buffer="") == "first prompt"

    def test_newer_walks_forward_and_restores_preserved_draft(self) -> None:
        """Forward recall restores the original draft past the newest entry."""
        navigator: PromptHistoryNavigator = PromptHistoryNavigator()
        navigator.record(text="first prompt")
        navigator.record(text="second prompt")

        assert navigator.older(current_buffer="draft") == "second prompt"
        assert navigator.older(current_buffer="ignored") == "first prompt"
        assert navigator.newer() == "second prompt"
        assert navigator.newer() == "draft"
        assert navigator.newer() is None

    def test_record_ignores_blank_prompts(self) -> None:
        """Blank prompts never enter recall history."""
        navigator: PromptHistoryNavigator = PromptHistoryNavigator()
        navigator.record(text="   ")

        assert navigator.older(current_buffer="") is None

    def test_clear_navigation_exits_history_mode(self) -> None:
        """Explicit navigation reset drops cursor and preserved draft."""
        navigator: PromptHistoryNavigator = PromptHistoryNavigator()
        navigator.record(text="first prompt")
        assert navigator.older(current_buffer="draft") == "first prompt"
        assert navigator.is_navigating is True

        navigator.clear_navigation()

        assert navigator.is_navigating is False
        assert navigator.newer() is None

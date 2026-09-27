"""Tests for the slash suggestion engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.tui.slash_router import SlashRouter
from src.tui.slash_suggestion_engine import SlashSuggestionEngine


class TestSlashSuggestionEngine:
    """Pure suggestion-state generation for slash composition."""

    def test_slash_opens_full_command_list(self) -> None:
        """A bare slash shows all registry-backed commands."""
        engine: SlashSuggestionEngine = SlashSuggestionEngine(
            registry=SlashRouter.registry(),
        )

        state = engine.evaluate(
            buffer_text="/",
            active_model_name="claude-sonnet-4-6",
        )

        assert state.visible is True
        assert state.rows[0].label == "/help"
        assert any(row.label == "/model" for row in state.rows)
        assert any(row.label == "/new" for row in state.rows)
        assert any(row.label == "/rename" for row in state.rows)

    def test_partial_command_sets_ghost_suffix(self) -> None:
        """A partial command exposes the remaining best-match suffix."""
        engine: SlashSuggestionEngine = SlashSuggestionEngine(
            registry=SlashRouter.registry(),
        )

        state = engine.evaluate(
            buffer_text="/mo",
            active_model_name="claude-sonnet-4-6",
        )

        assert state.visible is True
        assert state.rows[0].label == "/model"
        assert state.ghost_suffix == "del"

    def test_new_and_rename_commands_insert_trailing_space(self) -> None:
        """Free-text naming commands insert a trailing space on acceptance."""
        engine: SlashSuggestionEngine = SlashSuggestionEngine(
            registry=SlashRouter.registry(),
        )

        new_state = engine.evaluate(
            buffer_text="/ne",
            active_model_name="claude-sonnet-4-6",
        )
        rename_state = engine.evaluate(
            buffer_text="/ren",
            active_model_name="claude-sonnet-4-6",
        )

        assert new_state.rows[0].label == "/new"
        assert new_state.rows[0].insert_text == "/new "
        assert new_state.ghost_suffix == "w"
        assert rename_state.rows[0].label == "/rename"
        assert rename_state.rows[0].insert_text == "/rename "
        assert rename_state.ghost_suffix == "ame"

    def test_model_argument_mode_replaces_only_argument_span(self) -> None:
        """Completed `/model` pivots into model rows and narrows replacement span."""
        engine: SlashSuggestionEngine = SlashSuggestionEngine(
            registry=SlashRouter.registry(),
        )

        with patch(
            "src.tui.model_catalog.CredentialResolver.resolve",
            side_effect=lambda *, provider: object(),
        ):
            state = engine.evaluate(
                buffer_text="/model g",
                active_model_name="gpt-5.4",
            )

        assert state.visible is True
        assert state.replacement_start == len("/model ")
        assert state.rows[0].label.startswith("g")

    def test_model_rows_include_provider_and_auth_detail(self) -> None:
        """Model suggestion rows explain provider and auth readiness."""
        engine: SlashSuggestionEngine = SlashSuggestionEngine(
            registry=SlashRouter.registry(),
        )

        with patch(
            "src.tui.model_catalog.CredentialResolver.resolve",
            return_value=None,
        ):
            state = engine.evaluate(
                buffer_text="/model claude",
                active_model_name="gpt-5.4",
            )

        assert state.visible is True
        assert "anthropic" in (state.rows[0].detail or "")
        assert "requires /auth" in (state.rows[0].detail or "")

    def test_model_argument_mode_includes_astra_without_catalog_discovery(self) -> None:
        """Real autocomplete projects Astra from the static catalog without discovery."""
        engine: SlashSuggestionEngine = SlashSuggestionEngine(
            registry=SlashRouter.registry(),
        )
        forbidden_discovery: MagicMock = MagicMock(side_effect=AssertionError("discovery forbidden"))

        with (
            patch(
                "src.tui.model_catalog.CredentialResolver.resolve",
                side_effect=lambda *, provider: object(),
            ),
            patch(
                "src.agents.model_catalog.service.ProviderModelDiscoveryService.refresh",
                forbidden_discovery,
            ),
        ):
            state = engine.evaluate(
                buffer_text="/model gpt-6-as",
                active_model_name="gpt-5.4",
            )

        assert state.visible is True
        assert [row.label for row in state.rows] == ["gpt-6-astra"]
        forbidden_discovery.assert_not_called()

    def test_model_argument_mode_includes_codex_models(self) -> None:
        """The model suggestion list surfaces all OpenAI Codex variants."""
        engine: SlashSuggestionEngine = SlashSuggestionEngine(
            registry=SlashRouter.registry(),
        )

        with patch(
            "src.tui.model_catalog.CredentialResolver.resolve",
            side_effect=lambda *, provider: object(),
        ):
            state = engine.evaluate(
                buffer_text="/model ",
                active_model_name="gpt-5.4",
            )

        assert state.visible is True
        labels: list[str] = [row.label for row in state.rows]
        assert "gpt-5-codex" in labels
        assert "gpt-5.3-codex" in labels
        assert "gpt-5.2-codex" in labels
        assert "gpt-5.3-codex-spark" in labels

    def test_highlight_delta_wraps_across_rows(self) -> None:
        """Highlight movement wraps through the available rows."""
        engine: SlashSuggestionEngine = SlashSuggestionEngine(
            registry=SlashRouter.registry(),
        )

        state = engine.evaluate(
            buffer_text="/",
            active_model_name="claude-sonnet-4-6",
        )
        wrapped = state.with_highlight_delta(delta=-1)

        assert wrapped.highlighted_index == len(state.rows) - 1

    def test_workflows_command_appears_in_suggestions(self) -> None:
        """``/work`` suggests the registry-backed ``/workflows`` command (spec 57.a.6)."""
        engine: SlashSuggestionEngine = SlashSuggestionEngine(
            registry=SlashRouter.registry(),
        )

        state = engine.evaluate(
            buffer_text="/work",
            active_model_name="claude-sonnet-4-6",
        )

        assert state.visible is True
        assert any(row.label == "/workflows" for row in state.rows)

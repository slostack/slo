"""Bounded offline OpenRouter picker regression tests."""

from __future__ import annotations

from src.tui.components.chat_transcript.component import ChatTranscript
from unittest.mock import patch

import pytest

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.tui.model_catalog import ModelSuggestionEntryDAO, _project_rows
from src.tui.slash_command_registry import SlashCommandRegistry
from src.tui.slash_suggestion_engine import (
    SlashSuggestionEngine,
    SlashSuggestionRowDAO,
    SlashSuggestionStateDAO,
)
from src.tui.widgets.slash_suggestion_menu import SlashSuggestionMenu
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from langchain_core.messages import AIMessage
from pathlib import Path
from uuid import uuid4


def _picker_entry(*, model_name: str, display_name: str) -> ModelSuggestionEntryDAO:
    """Build one local picker row without catalog, store, or network access.

    Args:
        model_name (str): Exact canonical route inserted into the prompt.
        display_name (str): Literal user-facing model label.

    Returns:
        ModelSuggestionEntryDAO: One deterministic OpenRouter presentation row.
    """
    return ModelSuggestionEntryDAO(
        model_name=model_name,
        display_name=display_name,
        provider=ProviderName.OPENROUTER,
        is_active=False,
        requires_auth=False,
        reasoning_summary="provider default",
        support_tier_label="auto-discovered",
    )


def test_empty_query_orders_active_recent_first_class_and_remaining_rows() -> None:
    """Keep the specified blank-query priority while deduplicating recent selections."""
    engine: SlashSuggestionEngine = SlashSuggestionEngine(registry=SlashCommandRegistry(commands=[]))
    engine.record_selection(model_name="recent")
    engine.record_selection(model_name="recent")
    entries: list[ModelSuggestionEntryDAO] = [
        _picker_entry(model_name="lexical", display_name="Lexical"),
        _picker_entry(model_name="first-class", display_name="First class").model_copy(
            update={"support_tier_label": None}
        ),
        _picker_entry(model_name="recent", display_name="Recent"),
        _picker_entry(model_name="active", display_name="Active").model_copy(update={"is_active": True}),
    ]

    ordered_entries = engine._empty_query_entries(entries=entries)

    assert [entry.model_name for entry in ordered_entries] == ["active", "recent", "first-class", "lexical"]


def test_model_suggestions_when_catalog_has_many_rows_are_bounded() -> None:
    """Ensure picker matching remains local and caps candidates before painting."""
    engine: SlashSuggestionEngine = SlashSuggestionEngine(registry=SlashCommandRegistry(commands=[]))
    entries: list[ModelSuggestionEntryDAO] = [
        _picker_entry(
            model_name=f"openrouter:vendor/sonnet-{index}",
            display_name=f"Sonnet {index}",
        )
        for index in range(1000)
    ]

    rows, total = engine._bounded_model_rows(query="sonnet", entries=entries)

    assert len(rows) == 25
    assert total == 1000
    assert rows[0].insert_text == "openrouter:vendor/sonnet-0"


def test_model_suggestions_when_display_name_matches_insert_exact_canonical_route() -> None:
    """Search display text case-insensitively while retaining route identity for insertion."""
    engine: SlashSuggestionEngine = SlashSuggestionEngine(registry=SlashCommandRegistry(commands=[]))
    entries: list[ModelSuggestionEntryDAO] = [
        _picker_entry(
            model_name="openrouter:vendor/opaque-id",
            display_name="Claude Sonnet Experimental",
        )
    ]

    with patch("src.tui.slash_suggestion_engine.model_suggestion_entries", return_value=entries) as rows:
        state = engine.evaluate(
            buffer_text="/model SONNET",
            active_model_name="gpt-5.4",
        )

    rows.assert_called_once_with(active_model_name="gpt-5.4")
    assert state.visible is True
    assert state.rows[0].insert_text == "openrouter:vendor/opaque-id"
    assert state.rows[0].label == "openrouter:vendor/opaque-id"
    assert state.replacement_start == len("/model ")
    assert state.replacement_end == len("/model SONNET")
    assert state.total_matches == 1


def test_model_suggestions_when_id_and_display_match_ranks_exact_id_first() -> None:
    """Rank exact IDs before canonical and display-name prefixes deterministically."""
    engine: SlashSuggestionEngine = SlashSuggestionEngine(registry=SlashCommandRegistry(commands=[]))
    entries: list[ModelSuggestionEntryDAO] = [
        _picker_entry(model_name="openrouter:vendor/sonnet-extended", display_name="Other"),
        _picker_entry(model_name="openrouter:vendor/id", display_name="Sonnet"),
        _picker_entry(model_name="sonnet", display_name="Different"),
    ]

    with patch("src.tui.slash_suggestion_engine.model_suggestion_entries", return_value=entries):
        state = engine.evaluate(buffer_text="/model sonnet", active_model_name="gpt-5.4")

    assert [row.insert_text for row in state.rows] == [
        "sonnet",
        "openrouter:vendor/id",
        "openrouter:vendor/sonnet-extended",
    ]


def test_model_suggestions_when_more_than_twenty_five_match_keeps_total_count() -> None:
    """Expose the total candidate count while keeping rendered work capped at 25 rows."""
    engine: SlashSuggestionEngine = SlashSuggestionEngine(registry=SlashCommandRegistry(commands=[]))
    entries: list[ModelSuggestionEntryDAO] = [
        _picker_entry(model_name=f"openrouter:vendor/model-{index}", display_name=f"Model {index}")
        for index in range(30)
    ]

    with patch("src.tui.slash_suggestion_engine.model_suggestion_entries", return_value=entries):
        state = engine.evaluate(buffer_text="/model model", active_model_name="gpt-5.4")

    assert len(state.rows) == 25
    assert state.total_matches == 30


def _build_tui_session() -> SloAgentSession:
    """Build a preconstructed local session for painted picker interaction.

    Returns:
        SloAgentSession: A session that cannot create provider network traffic.
    """
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="ok")])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


def test_suggestion_menu_when_candidates_exceed_cap_paints_safe_count_footer() -> None:
    """Paint a literal bounded count rather than all matching OpenRouter rows."""
    state = SlashSuggestionStateDAO(
        visible=True,
        rows=[
            SlashSuggestionRowDAO(
                insert_text="openrouter:vendor/model-0",
                label="openrouter:vendor/model-0",
                detail="<untrusted & literal>",
            )
        ],
        total_matches=30,
    )

    rendered = SlashSuggestionMenu._render_lines(state=state)

    assert "Showing 1 of 30 — type to narrow" in rendered
    assert "<untrusted & literal>" in rendered


async def test_tui_when_auth_has_no_landing_model_primes_cached_model_search() -> None:
    """Keep the current route and prime `/model` rather than auto-selecting a remote route."""
    app = SloTUI(session=_build_tui_session())

    async with app.run_test(size=(60, 15)) as pilot:
        await pilot.pause()
        app._on_auth_dismissed(
            CredentialDAO(
                provider=ProviderName.OPENROUTER,
                auth_type=AuthType.API_KEY,
                access_token="synthetic-test-key",
            )
        )
        await pilot.pause()

        assert app._input is not None
        assert app._input.text == "/model "


@pytest.mark.parametrize("size", [(80, 24), (60, 15)])
@pytest.mark.parametrize(
    "reasoning,expected",
    [
        ({"supported_efforts": ["none"], "mandatory": False}, "reasoning disable supported"),
        ({"supported_efforts": ["low", "high"]}, "reasoning low, high; provider default"),
    ],
)
async def test_mounted_picker_paints_reasoning_disable_evidence(
    size: tuple[int, int],
    reasoning: dict[str, object],
    expected: str,
) -> None:
    """Require real normal-path paint, then prove hidden render text cannot satisfy it."""
    from src.agents.model_catalog.seed import SeedModelCatalog
    from src.tui.authentication.auth_screen import AuthenticationScreen
    from tests.agents.model_catalog.test_openrouter_converter_metadata import _entry
    from tests.tui.authentication._painted_output import assert_widget_painted

    entry = _entry(reasoning=reasoning)
    snapshot = SeedModelCatalog.load().model_copy(update={"entries": {entry.model_name: entry}})
    entries = _project_rows(snapshot=snapshot, active_model_name=entry.model_name, statuses={})
    app = SloTUI(session=_build_tui_session())

    with patch("src.tui.slash_suggestion_engine.model_suggestion_entries", return_value=entries):
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            if isinstance(app.screen, AuthenticationScreen):
                await app.screen.action_cancel()
                await pilot.pause()
            assert app._input is not None
            app._input.load_text("/model openrouter")
            await pilot.pause()
            assert app._suggestion_menu is not None
            widget = app._suggestion_menu.query_one(".slash-suggestion-lines")
            assert_widget_painted(app=app, widget=widget, text=expected)
            try:
                widget.styles.visibility = "hidden"
                await pilot.pause()
                assert expected in str(widget.render())
                with pytest.raises(AssertionError, match="Expected widget paint"):
                    assert_widget_painted(app=app, widget=widget, text=expected)
            finally:
                widget.styles.visibility = "visible"
            await pilot.pause()
            assert_widget_painted(app=app, widget=widget, text=expected)


@pytest.mark.parametrize("size", [(80, 24), (60, 15)])
@pytest.mark.parametrize(
    "reasoning,expected",
    [
        ({"supported_efforts": ["none"], "mandatory": False}, "supported: off (reasoning disable supported)"),
        (
            {"supported_efforts": ["low", "high"]},
            "supported: low, high (provider default; disable unavailable)",
        ),
    ],
)
async def test_mounted_reasoning_router_paints_converted_controls(
    size: tuple[int, int],
    reasoning: dict[str, object],
    expected: str,
) -> None:
    """Paint the real bare-command result using the normal transcript adapter."""
    from src.agents.model_catalog.seed import SeedModelCatalog
    from src.agents.model_catalog.service import ModelCatalogService
    from src.tui.authentication.auth_screen import AuthenticationScreen
    from src.tui.slash_router import SlashRouter
    from tests.agents.model_catalog.test_openrouter_converter_metadata import _entry
    from tests.tui.test_slash_router import _build_session_stub
    from tests.tui.authentication._painted_output import assert_widget_painted

    entry = _entry(reasoning=reasoning)
    snapshot = SeedModelCatalog.load().model_copy(update={"entries": {entry.model_name: entry}})
    session = _build_session_stub()
    session.active_model_name = entry.model_name
    session.active_reasoning_level = "low"
    with patch.object(ModelCatalogService, "load", return_value=snapshot):
        result = await SlashRouter.dispatch(line="/reasoning", session=session)
    app = SloTUI(session=_build_tui_session())
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        if isinstance(app.screen, AuthenticationScreen):
            await app.screen.action_cancel()
            await pilot.pause()
        assert result.rendered is not None
        app.query_one(ChatTranscript).write_transcript_line(content=result.rendered, classes="tool-result")
        await pilot.pause()
        app.query_one("#transcript-scroll").scroll_end(animate=False)
        await pilot.pause()
        assert_widget_painted(app=app, widget=list(app.query(".tool-result"))[-1], text=expected)


async def test_tui_when_display_search_matches_inserts_exact_canonical_argument() -> None:
    """Exercise the mounted suggestion engine and input replacement at a small terminal size."""
    entries: list[ModelSuggestionEntryDAO] = [
        _picker_entry(
            model_name="openrouter:vendor/opaque-id",
            display_name="Claude Sonnet Experimental",
        )
    ]
    app = SloTUI(session=_build_tui_session())

    with patch("src.tui.slash_suggestion_engine.model_suggestion_entries", return_value=entries):
        async with app.run_test(size=(60, 15)) as pilot:
            await pilot.pause()
            assert app._input is not None
            app._input.load_text("/model sonnet")
            await pilot.pause()
            await pilot.press("tab")
            await pilot.pause()

            assert app._input.text == "/model openrouter:vendor/opaque-id"
            assert app._slash_suggestion_state.rows[0].label == "openrouter:vendor/opaque-id"

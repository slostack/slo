"""Unit tests for ``/tree`` slash command (sub-spec 42.a.1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tui.slash_router import SlashCommandResultDAO, SlashRouter
from src.tui.tree_export_format import TreeExportFormat


def _build_session_stub(*, workdir: Path = Path("/tmp/slo-fake")) -> MagicMock:
    """Build a ``SloAgentSession`` stub with the router-facing runtime surface."""
    session: MagicMock = MagicMock()
    session.workdir = workdir
    session.active_model_name = "claude-sonnet-4-6"
    session.active_reasoning_level = "high"
    session.is_running = False
    session.session_id = "test-session-id"
    session.history_store = MagicMock()
    session.history_store.load_events = AsyncMock(return_value=[])
    return session


class TestSlashTreeHandler:
    """Tests for ``SlashRouter._handle_tree``."""

    @pytest.mark.asyncio
    async def test_tree_command_default_format(self) -> None:
        """Bare ``/tree`` defaults to textual format."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/tree",
            session=session,
        )

        assert result.render_tree is not None
        assert result.tree_format == TreeExportFormat.TEXTUAL.value

    @pytest.mark.asyncio
    async def test_tree_command_markdown_format(self) -> None:
        """``/tree markdown`` returns markdown format."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/tree markdown",
            session=session,
        )

        assert result.render_tree is not None
        assert result.tree_format == TreeExportFormat.MARKDOWN.value

    @pytest.mark.asyncio
    async def test_tree_command_html_format(self) -> None:
        """``/tree html`` returns html format."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/tree html",
            session=session,
        )

        assert result.render_tree is not None
        assert result.tree_format == TreeExportFormat.HTML.value

    @pytest.mark.asyncio
    async def test_tree_command_invalid_format(self) -> None:
        """``/tree invalid`` returns usage error."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/tree invalid",
            session=session,
        )

        assert result.render_tree is None
        assert "usage" in (result.rendered or "").lower()

    @pytest.mark.asyncio
    async def test_tree_command_loads_events(self) -> None:
        """Handler loads events from session via ``load_events``."""
        session: MagicMock = _build_session_stub()

        await SlashRouter.dispatch(
            line="/tree",
            session=session,
        )

        session.history_store.load_events.assert_awaited_once_with(
            session_id="test-session-id"
        )

    @pytest.mark.asyncio
    async def test_tree_command_in_registry(self) -> None:
        """``/tree`` is discoverable in the command registry."""
        registry = SlashRouter.registry()
        command = registry.resolve(token="tree")

        assert command is not None
        assert command.name == "tree"
        assert command.display_order == 93

    @pytest.mark.asyncio
    async def test_tree_command_in_help(self) -> None:
        """``/tree`` appears in help output."""
        result = await SlashRouter._handle_help(rest="", session=MagicMock())

        assert result.rendered is not None
        assert "/tree" in result.rendered

    @pytest.mark.asyncio
    async def test_tree_command_no_history_store(self) -> None:
        """When history is disabled, render a helpful message."""
        session: MagicMock = _build_session_stub()
        session.history_store = None

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/tree",
            session=session,
        )

        assert "disabled" in (result.rendered or "").lower()
